"""视频转文字核心引擎：整合切片、ASR、校正、合并流程"""

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

    if not (30 <= chunk_duration <= 59):
        raise ValueError("chunk_duration 必须在 30-59 秒之间")

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

    try:
        # Step 1: 切片
        logger.info("Step 1/4: 切片处理（静音+能量分析）...")
        _, chunks = slice_mod.prepare_chunks(video_path, workspace, chunk_duration=chunk_duration)
        logger.info(f"  共 {len(chunks)} 个切片")

        # Step 2: ASR 识别
        logger.info("Step 2/4: ASR 识别（单线程，可能需要几分钟）...")
        results = asr.recognize_all(chunks, progress_callback=_progress_callback)

        # Step 3: 合并原始 Markdown
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

        # 清理
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
