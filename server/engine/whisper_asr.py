"""Whisper ASR 调用模块 — 使用 faster-whisper 实现本地离线识别"""

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

# None = 未初始化, False = 已确认不可用, Any = 可用
_whisper_model: any = False  # type: ignore[misc]
_model_name: str = "base"


def _load_whisper() -> any:
    """延迟加载 Whisper 模型（使用 faster-whisper）"""
    global _whisper_model, _model_name
    if _whisper_model is not False:
        return _whisper_model

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        logger.warning("faster-whisper 未安装，请运行: pip install faster-whisper")
        _whisper_model = None
        return None

    from ..config import get_whisper_config
    cfg = get_whisper_config()
    _model_name = cfg.get("model", "base")

    try:
        _whisper_model = WhisperModel(_model_name, device="cpu", compute_type="int8")
        logger.info(f"Whisper 模型加载成功: {_model_name} (faster-whisper, CPU)")
    except Exception as e:
        logger.warning(f"Whisper 模型加载失败: {e}")
        _whisper_model = None
        return None

    return _whisper_model


def is_available() -> bool:
    """检查 Whisper 是否可用"""
    return _load_whisper() is not None


def _recognize_in_subprocess(args: tuple) -> tuple[int, str | None]:
    """
    在子进程中执行识别（绕过 GIL，实现真正并行）。
    每个进程独立加载模型。
    """
    chunk_path, chunk_idx, model_name, language = args
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        options = {"language": language} if language else {"language": None}
        segments, _ = model.transcribe(str(chunk_path), **options)
        text = " ".join(segment.text for segment in segments).strip()
        return (chunk_idx, text)
    except Exception as e:
        return (chunk_idx, None)


def recognize_chunk(
    chunk_path: Path,
    chunk_idx: int,
) -> str | None:
    """
    使用 Whisper 识别单个音频切片。

    Returns:
        识别文本，失败返回 None
    """
    model = _load_whisper()
    if model is None:
        return None

    from ..config import get_whisper_config
    cfg = get_whisper_config()
    language = cfg.get("language", None)

    try:
        options = {}
        if language:
            options["language"] = language
        else:
            options["language"] = None  # Auto-detect

        segments, _ = model.transcribe(str(chunk_path), **options)
        # Join all segments into full text
        text = " ".join(segment.text for segment in segments).strip()
        logger.debug(f"片段 {chunk_idx} Whisper 识别完成: {text[:50]}...")
        return text
    except Exception as e:
        logger.warning(f"片段 {chunk_idx} Whisper 识别失败: {e}")
        return None


def recognize_all(
    chunks: list,
    progress_callback=None,
) -> dict[int, str | None]:
    """
    使用 Whisper 并行识别所有切片（多进程，真正的并行）。

    Args:
        chunks: Chunk 对象列表
        progress_callback: (idx, total, result, chunk) -> None

    Returns:
        {chunk_index: result_text or None}
    """
    results: dict[int, str | None] = {}

    from ..config import get_whisper_config
    cfg = get_whisper_config()
    model_name = cfg.get("model", "base")
    language = cfg.get("language", None)
    max_workers = cfg.get("num_workers", 4)  # 默认4进程
    logger.info(f"并行识别（多进程），使用 {max_workers} 个进程")

    # Prepare args for subprocesses: (chunk_path, chunk_idx, model_name, language)
    subprocess_args = [
        (chunk.path, chunk.index, model_name, language)
        for chunk in chunks
    ]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_chunk = {
            executor.submit(_recognize_in_subprocess, args): args[0:2]
            for args in subprocess_args
        }

        completed = 0
        for future in as_completed(future_to_chunk):
            chunk_path, idx = future_to_chunk[future]
            try:
                chunk_idx, result = future.result()
            except Exception as e:
                logger.warning(f"片段 {idx} 处理异常: {e}")
                result = None

            results[idx] = result
            completed += 1

            if progress_callback:
                # Find the corresponding chunk object
                chunk_obj = next((c for c in chunks if c.index == idx), None)
                if chunk_obj:
                    progress_callback(completed, len(chunks), result, chunk_obj)

    return results
