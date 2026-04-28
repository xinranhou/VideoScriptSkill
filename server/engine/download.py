"""网络视频下载：支持 B站、YouTube、抖音等平台，使用 yt-dlp"""

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional, Callable

logger = logging.getLogger(__name__)

# 断点续传文件大小阈值（100MB）
RESUME_THRESHOLD_BYTES = 100 * 1024 * 1024

# 下载超时时间（秒）- 网络不稳时设长一些
SOCKET_TIMEOUT = 600


class DownloadAbortRequested(Exception):
    """用户请求中止下载"""
    pass


def is_url(path: str) -> bool:
    """判断是否为网络路径"""
    return path.startswith("http://") or path.startswith("https://")


def _get_bilibili_headers(url: str) -> dict | None:
    """检测是否为 B站 CDN URL，返回 --add-headers 格式的 dict"""
    if "upos-hz-mirrorakam.akamaized.net" not in url and "upos-sz-mirrorcosov.bilivideo.com" not in url:
        return None
    # --add-headers 格式：key 是 "Field: Value"，value 是 None
    return {
        "Referer: https://www.bilibili.com": None,
        "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36": None,
    }


def _check_abort(output_path: Path, notify_callback: Optional[Callable] = None) -> None:
    """检查是否需要中止下载（用户手动触发）"""
    if notify_callback:
        try:
            # 通知外部检查是否中止，每分钟检查一次
            should_abort = notify_callback("check_abort", {"part_path": str(output_path)})
            if should_abort:
                raise DownloadAbortRequested("用户请求中止下载")
        except DownloadAbortRequested:
            raise
        except Exception:
            pass


def download_video(
    url: str,
    output_dir: str | Path | None = None,
    quality: Literal["best", "1080p", "720p", "480p"] = "best",
    progress_callback: Optional[Callable[[str, dict], None]] = None,
) -> str:
    """
    下载网络视频到本地，支持断点续传。

    Args:
        url: 视频 URL（B站、YouTube、抖音等）
        output_dir: 输出目录，默认使用临时目录
        quality: 视频质量，默认 best
        progress_callback: 进度回调 fn(action, data)，action 包括:
            - "start": 开始下载，data 含 url, output_dir
            - "progress": 下载进度，data 含 downloaded_bytes, total_bytes, speed
            - "check_abort": 外部检查是否请求中止，需返回 True/False
            - "complete": 下载完成，data 含 file_path
            - "retry": 重试中，data 含 attempt, reason

    Returns:
        下载后的本地视频文件路径

    Raises:
        DownloadAbortRequested: 用户请求中止下载
    """
    import yt_dlp

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="videoscripts_download_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"开始下载视频: {url}")

    # 首选 yt-dlp 带信息头下载（--add-headers 方式，与命令行一致）
    # B站等平台需要 Referer 才能访问 CDN 直链
    bili_headers = _get_bilibili_headers(url)

    def _make_ydl_opts(with_headers: bool) -> dict:
        """构建 yt-dlp 选项，with_headers=True 时添加 B站 headers"""
        opts: dict = {
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "quiet": True,  # 静默模式，由我们的 progress_callback 处理所有输出
            "no_warnings": True,
            "extract_flat": False,
            "socket_timeout": SOCKET_TIMEOUT,
            "concurrent_fragments": 4,
            "loglevel": "error",  # 抑制 yt-dlp 和 ffmpeg 的所有输出
        }
        # 质量选择
        if quality == "1080p":
            opts["format"] = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        elif quality == "720p":
            opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif quality == "480p":
            opts["format"] = "bestvideo[height<=480]+bestaudio/best[height<=480]"
        else:  # best
            opts["format"] = "bestvideo+bestaudio/best"
        if with_headers and bili_headers:
            # 使用 --add-headers 方式，与命令行 yt-dlp --add-headers 一致
            opts["add_headers"] = bili_headers
        return opts

    def _download_with_ydl(opts: dict) -> str:
        """执行 yt-dlp 下载，返回视频路径"""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("下载失败，无法获取视频信息")
            filename = ydl.prepare_filename(info)
            video_path = output_dir / filename
            if not video_path.exists():
                files = sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                if files:
                    video_path = files[0]
            return str(video_path)

    # yt-dlp 内部进度回调
    last_check_time = [0]

    def _yt_progress_hook(info: dict):
        if progress_callback and info["status"] == "downloading":
            now = time.time()
            if now - last_check_time[0] >= 0.5:  # 降低阈值到 0.5 秒，确保实时显示
                last_check_time[0] = now
                downloaded = info.get("downloaded_bytes", 0)
                total = info.get("total_bytes") or info.get("total_bytes_estimate", 0)
                speed = info.get("speed", 0)
                progress_callback("progress", {
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "speed": speed,
                })

    # 通知开始下载
    if progress_callback:
        progress_callback("start", {"url": url, "output_dir": str(output_dir)})

    # 策略1: yt-dlp 带信息头优先尝试
    ydl_opts = _make_ydl_opts(with_headers=True)
    ydl_opts["progress_hooks"] = [_yt_progress_hook]

    try:
        logger.info("尝试 yt-dlp 带信息头下载...")
        video_path = _download_with_ydl(ydl_opts)
        logger.info(f"视频下载完成（带信息头）: {video_path}")
        if progress_callback:
            progress_callback("complete", {"file_path": video_path})
        return video_path
    except DownloadAbortRequested:
        raise
    except Exception as e:
        logger.warning(f"yt-dlp 带信息头下载失败: {e}")

    # 策略2: yt-dlp 不带信息头重试
    ydl_opts = _make_ydl_opts(with_headers=False)
    ydl_opts["progress_hooks"] = [_yt_progress_hook]

    try:
        logger.info("尝试 yt-dlp 不带信息头下载...")
        video_path = _download_with_ydl(ydl_opts)
        logger.info(f"视频下载完成（不带信息头）: {video_path}")
        if progress_callback:
            progress_callback("complete", {"file_path": video_path})
        return video_path
    except DownloadAbortRequested:
        raise
    except Exception as e:
        logger.warning(f"yt-dlp 不带信息头下载失败: {e}")

    # 策略3: ffmpeg 后备下载
    logger.warning("尝试 ffmpeg 后备下载")
    output_path = output_dir / "video.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and output_path.exists():
            logger.info(f"视频下载完成（ffmpeg 后备）: {output_path}")
            if progress_callback:
                progress_callback("complete", {"file_path": str(output_path)})
            return str(output_path)
        else:
            raise RuntimeError(f"ffmpeg 下载失败: {result.stderr[:200]}")
    except DownloadAbortRequested:
        raise
    except Exception as e:
        raise RuntimeError(f"下载异常: {e}")


def download_audio(url: str, output_dir: str | Path | None = None) -> str:
    """
    下载网络视频并提取音频。

    Args:
        url: 视频 URL
        output_dir: 输出目录

    Returns:
        音频文件路径 (wav 或 m4a)
    """
    import yt_dlp

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="videoscripts_audio_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"提取音频: {url}")

    ydl_opts: dict = {
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "loglevel": "error",
        "format": "bestaudio/best",
        "socket_timeout": SOCKET_TIMEOUT,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
    }

    # B站 CDN 需要特殊 headers（--add-headers 格式）
    bili_headers = _get_bilibili_headers(url)
    if bili_headers:
        ydl_opts["add_headers"] = bili_headers

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("提取失败，无法获取视频信息")

            filename = ydl.prepare_filename(info)
            # 替换扩展名为 wav
            audio_path = output_dir / (Path(filename).stem + ".wav")

            if not audio_path.exists():
                files = sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
                for f in files:
                    if f.suffix in (".wav", ".m4a", ".mp3"):
                        audio_path = f
                        break

            logger.info(f"音频提取完成: {audio_path}")
            return str(audio_path)

    except yt_dlp.utils.DownloadError as e:
        raise RuntimeError(f"音频提取失败: {e}")
    except Exception as e:
        raise RuntimeError(f"音频提取异常: {e}")
