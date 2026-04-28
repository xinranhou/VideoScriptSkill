"""配置文件读写模块"""

import json
import os
from pathlib import Path
from typing import Any, Literal

_CONFIG_PATH = Path.home() / ".config" / "videoscripts" / "config.json"


def get_config_path() -> Path:
    return _CONFIG_PATH


def ensure_config_dir() -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    """读取本地配置文件，不存在则返回空字典"""
    if not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict[str, Any]) -> None:
    """保存配置到本地文件"""
    ensure_config_dir()
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_tencent_creds() -> dict[str, str]:
    """获取腾讯云凭证"""
    config = load_config()
    tencent = config.get("tencent", {})
    secret_id = tencent.get("secret_id", "")
    secret_key = tencent.get("secret_key", "")
    if not secret_id or not secret_key:
        raise ValueError(
            "腾讯云凭证未配置。请先运行 install.sh 或手动编辑 "
            f"{_CONFIG_PATH} 配置 secret_id 和 secret_key。"
        )
    return {
        "secret_id": secret_id,
        "secret_key": secret_key,
        "region": tencent.get("region", "ap-guangzhou"),
    }


def get_asr_config() -> dict[str, Any]:
    """获取 ASR 配置"""
    config = load_config()
    return config.get(
        "asr",
        {
            "engine": "16k_zh",
            "voice_format": "wav",
            "sample_rate": 16000,
            "chunk_duration": 45,
            "max_retries": 3,
            "retry_base_delay": 3,
            "batch_sleep_seconds": 2,
            "batch_size": 10,
        },
    )


def get_asr_engine() -> Literal["tencent", "whisper"]:
    """获取当前选用的 ASR 引擎"""
    config = load_config()
    engine = config.get("asr_engine", "whisper")
    if engine not in ("tencent", "whisper"):
        engine = "whisper"
    return engine  # type: ignore[return-value]


def get_whisper_config() -> dict[str, Any]:
    """获取 Whisper 配置"""
    config = load_config()
    return config.get(
        "whisper",
        {
            "model": "base",
            "language": None,  # None = 自动检测
            "task": "transcribe",
        },
    )


def get_minimax_key() -> str:
    """获取 MiniMax API key（环境变量优先，其次配置文件"""
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if key:
        return key
    config = load_config()
    key = config.get("minimax", {}).get("api_key", "").strip()
    return key
