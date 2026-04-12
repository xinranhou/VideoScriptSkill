"""视频切片模块：使用 ffmpeg 按静音点和能量分析将视频切分为 30-59 秒的片段"""

import logging
import os
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """单个音频切片"""
    index: int           # 片段序号（0 起）
    start_sec: float     # 起始时间（秒）
    end_sec: float       # 结束时间（秒）
    path: Path           # 文件路径


# ---------------------------------------------------------------------------
# 公共函数
# ---------------------------------------------------------------------------

def check_ffmpeg() -> bool:
    """检测 ffmpeg 是否可用"""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_duration(file_path: str | Path) -> float:
    """获取音视频时长（秒）"""
    # Try ffprobe first, fall back to ffmpeg if not available
    for cmd in ["ffprobe", "ffmpeg"]:
        try:
            if cmd == "ffprobe":
                result = subprocess.run(
                    [
                        "ffprobe",
                        "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(file_path),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                return float(result.stdout.strip())
            else:
                # ffmpeg fallback: parse duration from stderr
                result = subprocess.run(
                    [cmd, "-i", str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                import re
                match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", result.stderr)
                if match:
                    h, m, s = match.groups()
                    return float(h) * 3600 + float(m) * 60 + float(s)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    raise FileNotFoundError("Neither ffprobe nor ffmpeg found in PATH")


def extract_audio(video_path: str | Path, output_path: str | Path) -> None:
    """从视频中提取 16kHz 单声道 WAV 音频"""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video_path),
            "-ar", "16000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# 静音检测
# ---------------------------------------------------------------------------

def detect_silence(
    audio_path: str | Path,
    min_silence_len: float = 0.4,
    silence_thresh: float = -42,
) -> list[dict]:
    """
    检测音频中的静音段，返回 [{start, end}, ...]（秒）。

    参数优化说明：
    - min_silence_len: 0.4s（说话间隙通常 > 0.3s）
    - silence_thresh: -42dB（更灵敏，减少漏检）
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-i", str(audio_path),
            "-af", f"silencedetect=noise={silence_thresh}dB:d={min_silence_len}",
            "-f", "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    silence_ranges = []
    lines = result.stderr.split("\n")
    start = None
    for line in lines:
        if "silencedetect" not in line:
            continue
        if "silence_start" in line:
            start = float(line.split("silence_start: ")[-1].strip())
        elif "silence_end" in line and start is not None:
            end = float(line.split("silence_end: ")[1].split(" ")[0].strip())
            silence_ranges.append({"start": start, "end": end})
            start = None
    return silence_ranges


# ---------------------------------------------------------------------------
# 能量分析（静音检测的兜底）
# ---------------------------------------------------------------------------

def find_pause_points(
    audio_path: str | Path,
    min_pause_sec: float = 0.5,
    window_ms: int = 50,
    energy_threshold_ratio: float = 0.15,
    max_points: int = 50,
) -> list[float]:
    """
    基于短时能量找音频中的自然停顿点。

    策略：计算每 50ms 的能量（RMS），找到能量 < 全局均值×0.15 的段落，
    取其中心作为候选切割点。

    Returns:
        停顿时间点列表（秒），已去重排序
    """
    try:
        with wave.open(str(audio_path), "rb") as wf:
            n_frames = wf.getnframes()
            sample_rate = wf.getframerate()
            frames = wf.readframes(n_frames)
            # 转为 int16 数组
            samples = struct.unpack(f"<{n_frames}h", frames)

        window_size = int(sample_rate * window_ms / 1000)
        n_windows = len(samples) // window_size

        # 计算每窗口 RMS
        energies = []
        for i in range(n_windows):
            chunk = samples[i * window_size : (i + 1) * window_size]
            rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5
            energies.append(rms)

        if not energies:
            return []

        mean_energy = sum(energies) / len(energies)
        threshold = mean_energy * energy_threshold_ratio

        # 找低能量窗口段
        pause_points = []
        in_pause = False
        pause_start = 0.0
        window_sec = window_ms / 1000.0

        for i, e in enumerate(energies):
            t = i * window_sec
            if e < threshold:
                if not in_pause:
                    in_pause = True
                    pause_start = t
            else:
                if in_pause:
                    duration = t - pause_start
                    if duration >= min_pause_sec:
                        pause_center = pause_start + duration / 2
                        pause_points.append(pause_center)
                    in_pause = False

        # 去重（间隔 < 1s 合并）
        merged = []
        for pt in sorted(pause_points):
            if not merged or pt - merged[-1] > 1.0:
                merged.append(pt)

        return merged[:max_points]

    except Exception as e:
        logger.warning(f"能量分析失败: {e}")
        return []


# ---------------------------------------------------------------------------
# 切割点查找
# ---------------------------------------------------------------------------

def _find_cut_point(
    target: float,
    silence_ranges: list[dict],
    energy_points: list[float],
    pos: float,
    min_duration: float,
    max_offset: float = 2.0,
) -> float:
    """
    在 target 附近找到最佳切割点。

    优先级：
    1. 静音段中点（± max_offset 秒内）
    2. 能量停顿点（± max_offset 秒内）
    3. 硬切 target
    """
    candidates = []

    # 1. 静音段
    for seg in silence_ranges:
        mid = (seg["start"] + seg["end"]) / 2
        offset = abs(mid - target)
        if offset <= max_offset and mid > pos + min_duration:
            candidates.append((offset * 0.5, mid))  # 静音优先（乘 0.5 降低权重）

    # 2. 能量停顿点
    for pt in energy_points:
        offset = abs(pt - target)
        if offset <= max_offset and pt > pos + min_duration:
            candidates.append((offset, pt))

    if candidates:
        candidates.sort()
        return candidates[0][1]

    # 3. 硬切
    return target


# ---------------------------------------------------------------------------
# 核心切片逻辑
# ---------------------------------------------------------------------------

def split_audio_by_chunks(
    audio_path: str | Path,
    output_dir: str | Path,
    chunk_duration: int = 45,
    min_duration: int = 30,
    max_offset: float = 2.0,
) -> list[Chunk]:
    """
    将音频切分为 30-59 秒的自然片段。

    策略：
    - 以 chunk_duration 为目标切分点
    - 优先在静音段中点切割（± 2s 内）
    - 次选能量停顿点（± 2s 内）
    - 硬切作为兜底
    - 自动分析音频，找最佳停顿点
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    duration = get_duration(audio_path)
    logger.info(f"音频总时长 {duration:.0f}s，开始切片...")

    # 预分析（各只跑一次）
    silence_ranges = detect_silence(audio_path)
    logger.debug(f"检测到 {len(silence_ranges)} 个静音段")

    energy_points = find_pause_points(audio_path)
    logger.debug(f"能量分析找到 {len(energy_points)} 个停顿点")

    chunks: list[Chunk] = []
    chunk_idx = 0
    pos = 0.0

    while pos < duration:
        next_pos = pos + chunk_duration
        if next_pos > duration:
            next_pos = duration

        # 最后一个片段不允许比 min_duration 更短
        if next_pos == duration and next_pos - pos < min_duration:
            if chunks:
                # 合并到上一个片段
                prev = chunks[-1]
                chunks[-1] = Chunk(
                    index=prev.index,
                    start_sec=prev.start_sec,
                    end_sec=duration,
                    path=prev.path,
                )
                # 重新生成最后一片
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(audio_path),
                        "-ss", str(prev.start_sec),
                        "-to", str(duration),
                        "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                        str(prev.path),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
            break

        # 找最佳切割点
        cut = _find_cut_point(
            target=(pos + next_pos) / 2,
            silence_ranges=silence_ranges,
            energy_points=energy_points,
            pos=pos,
            min_duration=min_duration,
            max_offset=max_offset,
        )
        actual_end = min(cut, next_pos)
        if actual_end <= pos + min_duration:
            actual_end = next_pos

        chunk_path = output_dir / f"c_{int(pos)}_{int(actual_end)}.wav"

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-ss", str(pos),
                "-to", str(actual_end),
                "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                str(chunk_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        chunks.append(Chunk(index=chunk_idx, start_sec=pos, end_sec=actual_end, path=chunk_path))
        chunk_idx += 1
        pos = actual_end

    logger.info(f"切片完成: {len(chunks)} 个片段")
    for c in chunks:
        logger.debug(f"  [{c.start_sec:.0f}s - {c.end_sec:.0f}s] {c.path.name}")

    return chunks


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def prepare_chunks(
    video_path: str | Path,
    workspace_dir: str | Path | None = None,
    chunk_duration: int = 45,
) -> tuple[Path, list[Chunk]]:
    """
    准备音频切片：如果是视频先提取音频，再切片。

    Args:
        video_path: 视频文件路径
        workspace_dir: 工作目录，默认使用系统临时目录
        chunk_duration: 目标切片时长（秒），需在 30-59 之间

    Returns:
        (workspace_dir, chunks) — workspace 目录和切片列表
    """
    video_path = Path(video_path)
    workspace_dir = Path(workspace_dir) if workspace_dir else Path(tempfile.mkdtemp(prefix="videoscripts_"))

    suffix = video_path.suffix.lower()
    if suffix == ".wav":
        audio_path = video_path
    elif suffix == ".mp4":
        audio_path = workspace_dir / "audio_extract.wav"
        extract_audio(video_path, audio_path)
    else:
        raise ValueError(f"不支持的视频格式: {suffix}，目前支持 mp4 和 wav")

    chunks_dir = workspace_dir / "chunks"
    chunks = split_audio_by_chunks(audio_path, chunks_dir, chunk_duration=chunk_duration)
    return workspace_dir, chunks
