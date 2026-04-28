"""视频转文字核心引擎：整合切片、ASR、校正、合并流程，支持断点续传"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional, Callable

from . import asr, correct, merge, slice as slice_mod, whisper_asr, download
from ..config import get_asr_engine

# 初始化日志配置
from ..logging_config import configure_logging
configure_logging()

logger = logging.getLogger(__name__)

# 单例工作区路径（跨调用保留，支持断点续传）
_workspace: Path | None = None

# 下载进度询问间隔（每10分钟询问一次用户是否继续）
DOWNLOAD_CHECK_INTERVAL_SEC = 600

# 用户未响应时继续等待的时间（秒）
DOWNLOAD_GRACE_PERIOD_SEC = 30


def _make_progress_callback(notify_callback=None):
    """创建进度回调函数，实时通知用户当前步骤和百分比"""
    import sys
    def callback(idx: int, total: int, result: str | None, chunk) -> None:
        status = "OK" if result else "FAIL"
        percent = int(idx * 100 / total)
        # 原地更新同一行，显示当前步骤和百分比
        line = f"\r[Step 3/5 ASR识别] {percent}% [{idx}/{total}] {status}"
        print(line, end="", file=sys.stderr, flush=True)
        sys.stderr.flush()
        logger.info(f"  [{idx}/{total}] {status}")
        if notify_callback:
            notify_callback(line)
    return callback


def _make_download_progress_callback(notify_callback=None):
    """创建下载进度回调，实时显示下载百分比和速度"""
    import sys

    def callback(action: str, data: dict):
        if action == "progress":
            downloaded = data.get("downloaded_bytes", 0) or 0
            total = data.get("total_bytes", 0) or 0
            speed = data.get("speed", 0) or 0
            speed_str = f"{speed / 1024:.1f}KB/s" if speed else "未知"

            if total > 0:
                percent = int(downloaded * 100 / total)
                downloaded_mb = downloaded / 1024 / 1024
                total_mb = total / 1024 / 1024
                line = f"\r[Step 1/5 下载中] {percent}% ({downloaded_mb:.1f}/{total_mb:.1f}MB, {speed_str})"
            else:
                downloaded_mb = downloaded / 1024 / 1024
                line = f"\r[Step 1/5 下载中] {downloaded_mb:.1f}MB ({speed_str})"

            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
            if notify_callback:
                notify_callback(line)
        elif action == "start":
            url = data.get("url", "")
            line = f"\r[Step 1/5 下载中] 开始下载..."
            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
            logger.info(f"开始下载: {url[:80]}...")
            if notify_callback:
                notify_callback(line)
        elif action == "complete":
            filepath = data.get("file_path", "")
            print(f"\r[Step 1/5 下载完成] {filepath}", file=sys.stderr, flush=True)
            sys.stderr.flush()
            logger.info(f"下载完成: {filepath}")
            if notify_callback:
                notify_callback(f"[Step 1/5 下载完成] {filepath}")
        elif action == "retry":
            attempt = data.get("attempt", 1)
            reason = data.get("reason", "")
            line = f"\r[Step 1/5 下载重试] 第{attempt}次: {reason[:50]}"
            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
            logger.info(f"下载重试 ({attempt}): {reason}")
            if notify_callback:
                notify_callback(line)

    return callback


def _make_slice_progress_callback(notify_callback=None):
    """将 slice 事件转换为进度字符串，透传给 notify_callback"""
    import sys

    def callback(action: str, data: dict):
        if action == "slice_start":
            line = f"\r[Step 2/5 切片] 开始切片，总时长 {data.get('duration', 0):.0f}s"
            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
        elif action == "analyze":
            step = data.get("step", "")
            line = f"\r[Step 2/5 切片] 分析音频（{step}）..."
            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
        elif action == "chunk":
            idx = data.get("index", 0)
            total = data.get("total_estimate", 0)
            start = data.get("start_sec", 0)
            end = data.get("end_sec", 0)
            line = f"\r[Step 2/5 切片] {idx}/{total} [{start:.0f}s - {end:.0f}s]"
            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
        elif action == "complete":
            line = f"\r[Step 2/5 切片完成] 共 {data.get('chunk_count', 0)} 个片段"
            print(line, end="", file=sys.stderr, flush=True)
            sys.stderr.flush()
        elif action == "audio_extract":
            status = data.get("status", "")
            if status == "start":
                print("\r[Step 2/5 切片] 提取音频...", end="", file=sys.stderr, flush=True)
                sys.stderr.flush()
            elif status == "done":
                print(f"\r[Step 2/5 切片] 音频提取完成", end="", file=sys.stderr, flush=True)
                sys.stderr.flush()
        if notify_callback:
            notify_callback(action, data)

    return callback


def _get_checkpoint_path(video_path: Path, workspace: Path) -> Path:
    """检查点文件路径：放在 workspace 下，以视频文件名命名"""
    return workspace / f".checkpoint_{video_path.stem}.json"


def _load_checkpoint(checkpoint_path: Path) -> dict[int, str | None]:
    """加载检查点，返回 {chunk_index: result_text}"""
    if not checkpoint_path.exists():
        return {}
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"检查点加载成功，已完成 {len(data)} 个片段")
        return {int(k): v for k, v in data.items()}
    except Exception as e:
        logger.warning(f"检查点加载失败: {e}，从头开始")
        return {}


def _save_checkpoint(checkpoint_path: Path, results: dict[int, str | None]) -> None:
    """保存检查点"""
    try:
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in results.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"检查点保存失败: {e}")


def _recognize_all_with_checkpoint(
    chunks: list,
    checkpoint: dict[int, str | None],
    checkpoint_path: Path,
    progress_callback=None,
) -> dict[int, str | None]:
    """
    带检查点的识别：跳过已完成片段，每完成一片立即保存检查点。
    根据配置选择腾讯云 ASR 或 Whisper 引擎。
    """
    results = dict(checkpoint)  # 已有结果并入结果集
    engine = get_asr_engine()

    if engine == "whisper":
        logger.info("使用 Whisper 引擎进行识别")
        if not whisper_asr.is_available():
            raise RuntimeError("Whisper 不可用，请检查是否安装: pip install openai-whisper")
        return _recognize_whisper_with_checkpoint(chunks, checkpoint, checkpoint_path, progress_callback)
    else:
        logger.info("使用腾讯云 ASR 引擎进行识别")
        return _recognize_tencent_with_checkpoint(chunks, checkpoint, checkpoint_path, progress_callback)


def _recognize_tencent_with_checkpoint(
    chunks: list,
    checkpoint: dict[int, str | None],
    checkpoint_path: Path,
    progress_callback=None,
) -> dict[int, str | None]:
    """腾讯云 ASR 带检查点识别"""
    results = dict(checkpoint)
    cfg = asr.get_asr_config()
    batch_size = cfg.get("batch_size", 10)
    batch_sleep = cfg.get("batch_sleep_seconds", 2)
    client = asr.build_client()

    completed = len(results)
    total = len(chunks)

    for i, chunk in enumerate(chunks):
        if chunk.index in results:
            logger.debug(f"  跳过已完成的片段 [{chunk.index + 1}/{total}]")
            completed += 1
            if progress_callback:
                progress_callback(completed, total, results[chunk.index], chunk)
            continue

        result = asr.recognize_chunk(client, chunk.path, i + 1)
        results[chunk.index] = result

        _save_checkpoint(checkpoint_path, results)
        completed += 1

        if progress_callback:
            progress_callback(i + 1, total, result, chunk)

        if completed % batch_size == 0:
            logger.debug(f"已完成 {completed} 片段，休眠 {batch_sleep} 秒")
            import time
            time.sleep(batch_sleep)

    return results


def _recognize_whisper_with_checkpoint(
    chunks: list,
    checkpoint: dict[int, str | None],
    checkpoint_path: Path,
    progress_callback=None,
) -> dict[int, str | None]:
    """Whisper ASR 带检查点识别（并行执行）"""
    results = dict(checkpoint)
    total = len(chunks)

    # 过滤出未完成的片段
    pending_chunks = [c for c in chunks if c.index not in results]
    if pending_chunks:
        logger.info(f"Whisper 并行识别 {len(pending_chunks)} 个待处理片段（{total - len(pending_chunks)} 个已从检查点恢复）")
        # 用 parallel 版本，保留增量保存检查点的能力
        partial_results = _recognize_whisper_parallel_with_checkpoint(
            pending_chunks, checkpoint_path, results.copy(), progress_callback, start_offset=len(results)
        )
        results.update(partial_results)
        _save_checkpoint(checkpoint_path, results)

    return results


def _recognize_whisper_parallel_with_checkpoint(
    chunks: list,
    checkpoint_path: Path,
    results: dict[int, str | None],
    progress_callback=None,
    start_offset: int = 0,
) -> dict[int, str | None]:
    """Whisper 并行识别，支持增量保存检查点"""
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed

    max_workers = min(os.cpu_count() or 4, 4)
    total = len(chunks)
    completed = start_offset

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk = {
            executor.submit(whisper_asr.recognize_chunk, chunk.path, chunk.index + 1): chunk
            for chunk in chunks
        }

        for future in as_completed(future_to_chunk):
            chunk = future_to_chunk[future]
            try:
                result = future.result()
            except Exception as e:
                logger.warning(f"片段 {chunk.index + 1} 处理异常: {e}")
                result = None

            results[chunk.index] = result
            completed += 1

            if progress_callback:
                progress_callback(completed, start_offset + total, result, chunk)

            # 每完成一个片段立即保存检查点
            _save_checkpoint(checkpoint_path, results)

    return results


def transcribe(
    video_path: str,
    output_format: Literal["markdown", "txt"] = "markdown",
    chunk_duration: int = 45,
    output_path: str | None = None,
    enable_translation: bool = False,
    notify_callback=None,
    timeout_seconds: int = 3600,
) -> str:
    """
    将视频文件转为文字脚本。

    Args:
        video_path: 视频文件路径（mp4、wav）或网络 URL
        output_format: 输出格式，目前仅支持 markdown
        chunk_duration: 切片时长（秒），需在 30-59 之间
        output_path: 输出文件路径，默认保存到 ./downloads/ 目录下
        enable_translation: 是否启用翻译为中文（默认 False）
        timeout_seconds: 超时秒数，默认 3600（1小时）

    Returns:
        Markdown 格式的文字脚本内容
    """
    global _workspace

    def check_timeout(label: str = ""):
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            raise TimeoutError(f"转录超时（已运行 {elapsed:.0f}s > {timeout_seconds}s）{label}")

    # 确定下载目录（用于保存 mp4 和转录文件）
    downloads_dir = Path("./downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)

    # 自动下载网络视频，保存到 downloads 目录
    if download.is_url(video_path):
        logger.info(f"检测到网络 URL，自动下载: {video_path}")
        # 从 URL 提取文件名作为保存名
        url_path = Path(video_path.split("?")[0].split("/")[-1])
        saved_video_path = downloads_dir / url_path.name
        # 如果已存在同名文件，跳过下载直接使用
        if saved_video_path.exists():
            logger.info(f"视频已存在，直接使用: {saved_video_path}")
            video_path = str(saved_video_path)
        else:
            video_path = download.download_video(
                video_path,
                output_dir=downloads_dir,
                progress_callback=_make_download_progress_callback(notify_callback),
            )
            logger.info(f"下载完成，本地路径: {video_path}")
            # 重命名下载的文件为原始文件名
            downloaded = Path(video_path)
            if downloaded.suffix in (".mp4", ".mkv", ".flv"):
                new_name = downloads_dir / url_path.name
                if downloaded != new_name:
                    downloaded.rename(new_name)
                    video_path = str(new_name)
                    logger.info(f"视频重命名: {video_path}")
    else:
        # 本地文件，复制到 downloads 目录一份
        video_path = Path(video_path)
        saved_video_path = downloads_dir / video_path.name
        if not saved_video_path.exists() and video_path.exists():
            shutil.copy2(video_path, saved_video_path)
            logger.info(f"本地视频已复制到: {saved_video_path}")
        video_path = str(video_path)

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"文件不存在: {video_path}")

    if not (15 <= chunk_duration <= 59):
        raise ValueError("chunk_duration 必须在 15-59 秒之间")

    video_path = Path(video_path)
    logger.info(f"开始转录: {video_path} (切片: {chunk_duration}s)")

    # 记录开始时间
    start_time = time.time()

    # 确定输出路径：默认保存到 downloads 目录
    if output_path:
        output_file = Path(output_path)
    else:
        video_name = video_path.stem
        output_file = downloads_dir / f"{video_name}_transcript.md"

    # 创建临时工作目录（仅用于切片和检查点，不保存 mp4）
    workspace = Path(tempfile.mkdtemp(prefix="videoscripts_"))
    _workspace = workspace
    logger.info(f"工作目录: {workspace}")

    # 检查点路径
    checkpoint_path = _get_checkpoint_path(video_path, workspace)

    try:
        # Step 2: 切片
        logger.info("Step 2/5: 切片处理（静音+能量分析）...")
        _, chunks = slice_mod.prepare_chunks(video_path, workspace, chunk_duration=chunk_duration, progress_callback=_make_slice_progress_callback(notify_callback))
        logger.info(f"  共 {len(chunks)} 个切片")
        check_timeout("（切片完成）")

        # Step 3: 加载检查点（如果存在）
        checkpoint = _load_checkpoint(checkpoint_path)

        # Step 3: ASR 识别（支持断点续传）
        engine = get_asr_engine()
        engine_name = "Whisper" if engine == "whisper" else "腾讯云 ASR"
        logger.info(f"Step 3/5: {engine_name} 识别（单线程，支持断点续传）...")
        if checkpoint:
            skipped = sum(1 for c in chunks if c.index in checkpoint)
            logger.info(f"  从检查点恢复，将跳过 {skipped} 个已完成的片段")
        results = _recognize_all_with_checkpoint(
            chunks, checkpoint, checkpoint_path,
            progress_callback=_make_progress_callback(notify_callback),
        )
        check_timeout("（ASR完成）")

        # Step 4: 合并原始 Markdown
        import sys
        print(f"\r[Step 4/5 合并] 合并 {len(chunks)} 个片段...", end="", file=sys.stderr, flush=True)
        logger.info("Step 4/5: 合并结果...")
        elapsed = time.time() - start_time
        raw_markdown = merge.merge_to_markdown(chunks, results, engine_name=engine_name, duration_sec=elapsed, translation=enable_translation)

        success = sum(1 for r in results.values() if r)
        fail = len(results) - success
        print(f"\r[Step 4/5 合并] 完成，成功 {success}，失败 {fail}", file=sys.stderr, flush=True)
        logger.info(f"  ASR 完成: {len(chunks)} 片段，成功 {success}，失败 {fail}")

        # Step 5: LLM 校正（始终启用）+ 翻译（可选）
        logger.info("Step 5/5: LLM 文本校正...")
        check_timeout("（开始校正前）")
        markdown = correct.correct_text(raw_markdown, enable_translation=enable_translation)
        check_timeout("（校正完成）")

        # 保存到文件
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown)
        logger.info(f"结果已保存: {output_file}")

        # 清理检查点（成功完成后删除）
        if checkpoint_path.exists():
            checkpoint_path.unlink()

        # 清理工作区和残留进程
        shutil.rmtree(workspace, ignore_errors=True)
        _workspace = None
        cleanup_processes()

        return markdown

    except TimeoutError:
        logger.error(f"转录超时（{timeout_seconds}s），工作目录保留在: {workspace}")
        cleanup_processes()
        raise
    except Exception:
        logger.exception(f"转录失败，工作目录保留在: {workspace}")
        cleanup_processes()
        raise


def cleanup_workspace() -> None:
    """清理上次调用的工作目录"""
    global _workspace
    if _workspace and _workspace.exists():
        shutil.rmtree(_workspace, ignore_errors=True)
        _workspace = None


def cleanup_processes() -> None:
    """清理残留的 whisper 模型进程，避免资源占用"""
    import subprocess
    import os
    pid = os.getpid()

    # 查找可能残留的 whisper 相关子进程
    try:
        result = subprocess.run(
            ["pgrep", "-f", "whisper|WhisperModel|faster-whisper"],
            capture_output=True, text=True
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    proc_pid = int(line)
                    if proc_pid != pid:
                        subprocess.run(["kill", "-9", str(proc_pid)], capture_output=True)
                except ValueError:
                    pass
    except Exception:
        pass

    # 清理工作区
    cleanup_workspace()
    logger.info("进程清理完成")
