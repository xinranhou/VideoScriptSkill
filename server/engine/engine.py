"""视频转文字核心引擎：整合切片、ASR、校正、合并流程，支持断点续传"""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from . import asr, correct, merge, slice as slice_mod

logger = logging.getLogger(__name__)

# 单例工作区路径（跨调用保留，支持断点续传）
_workspace: Path | None = None


def _progress_callback(idx: int, total: int, result: str | None, chunk) -> None:
    status = "OK" if result else "FAIL"
    snippet = result[:50] + "..." if result and len(result) > 50 else (result or "失败")
    logger.info(f"  [{idx}/{total}] {status}: {snippet}")


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
    """
    results = dict(checkpoint)  # 已有结果并入结果集
    cfg = asr.get_asr_config()
    batch_size = cfg.get("batch_size", 10)
    batch_sleep = cfg.get("batch_sleep_seconds", 2)
    client = asr.build_client()

    completed = len(results)
    total = len(chunks)

    for i, chunk in enumerate(chunks):
        if chunk.index in results:
            logger.debug(f"  跳过已完成的片段 [{chunk.index + 1}/{total}]")
            if progress_callback:
                progress_callback(chunk.index + 1, total, results[chunk.index], chunk)
            continue

        result = asr.recognize_chunk(client, chunk.path, i + 1)
        results[chunk.index] = result

        # 每完成一片立即写盘
        _save_checkpoint(checkpoint_path, results)
        completed += 1

        if progress_callback:
            progress_callback(i + 1, total, result, chunk)

        # 每 batch_size 片段休眠，防止 API 限流
        if completed % batch_size == 0:
            logger.debug(f"已完成 {completed} 片段，休眠 {batch_sleep} 秒")
            import time
            time.sleep(batch_sleep)

    return results


def transcribe(
    video_path: str,
    output_format: Literal["markdown", "txt"] = "markdown",
    chunk_duration: int = 45,
    enable_correction: bool = True,
    output_path: str | None = None,
) -> str:
    """
    将视频文件转为文字脚本。

    Args:
        video_path: 视频文件路径（mp4 或 wav）
        output_format: 输出格式，目前仅支持 markdown
        chunk_duration: 切片时长（秒），需在 30-59 之间
        enable_correction: 是否启用 LLM 文本校正
        output_path: 输出文件路径，默认保存到视频同目录下

    Returns:
        Markdown 格式的文字脚本内容
    """
    global _workspace

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"文件不存在: {video_path}")

    if not (15 <= chunk_duration <= 59):
        raise ValueError("chunk_duration 必须在 15-59 秒之间")

    video_path = Path(video_path)
    logger.info(f"开始转录: {video_path} (切片: {chunk_duration}s, 校正: {'开' if enable_correction else '关'})")

    # 确定输出路径：默认保存到视频同目录
    if output_path:
        output_file = Path(output_path)
    else:
        video_name = video_path.stem
        output_file = video_path.parent / f"{video_name}_transcript.md"

    # 创建临时工作目录
    workspace = Path(tempfile.mkdtemp(prefix="videoscripts_"))
    _workspace = workspace
    logger.info(f"工作目录: {workspace}")

    # 检查点路径
    checkpoint_path = _get_checkpoint_path(video_path, workspace)

    try:
        # Step 1: 切片
        logger.info("Step 1/4: 切片处理（静音+能量分析）...")
        _, chunks = slice_mod.prepare_chunks(video_path, workspace, chunk_duration=chunk_duration)
        logger.info(f"  共 {len(chunks)} 个切片")

        # Step 2: 加载检查点（如果存在）
        checkpoint = _load_checkpoint(checkpoint_path)

        # Step 3: ASR 识别（支持断点续传）
        logger.info("Step 2/4: ASR 识别（单线程，支持断点续传）...")
        if checkpoint:
            skipped = sum(1 for c in chunks if c.index in checkpoint)
            logger.info(f"  从检查点恢复，将跳过 {skipped} 个已完成的片段")
        results = _recognize_all_with_checkpoint(
            chunks, checkpoint, checkpoint_path,
            progress_callback=_progress_callback,
        )

        # Step 3.5: 合并原始 Markdown
        logger.info("Step 3/4: 合并结果...")
        raw_markdown = merge.merge_to_markdown(chunks, results)

        success = sum(1 for r in results.values() if r)
        fail = len(results) - success
        logger.info(f"  ASR 完成: {len(chunks)} 片段，成功 {success}，失败 {fail}")

        # Step 4: LLM 校正（可选）
        if enable_correction:
            logger.info("Step 4/4: LLM 文本校正...")
            markdown = correct.correct_text(raw_markdown)
        else:
            logger.info("Step 4/4: 跳过校正")
            markdown = raw_markdown

        # 保存到文件
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown)
        logger.info(f"结果已保存: {output_file}")

        # 清理检查点（成功完成后删除）
        if checkpoint_path.exists():
            checkpoint_path.unlink()

        # 清理工作区
        shutil.rmtree(workspace, ignore_errors=True)
        _workspace = None

        return markdown

    except Exception:
        logger.exception(f"转录失败，工作目录保留在: {workspace}")
        raise


def cleanup_workspace() -> None:
    """清理上次调用的工作目录"""
    global _workspace
    if _workspace and _workspace.exists():
        shutil.rmtree(_workspace, ignore_errors=True)
        _workspace = None
