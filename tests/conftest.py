"""Pytest fixtures"""

import pytest
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 测试视频（用户提供，已复制到 tests/fixtures）
TEST_VIDEO = PROJECT_ROOT / "tests" / "fixtures" / "VideoSample.mp4"
TEST_AUDIO = PROJECT_ROOT / "tests" / "fixtures" / "audioSample.wav"


@pytest.fixture
def sample_video() -> Path:
    if not TEST_VIDEO.exists():
        pytest.skip(f"测试视频不存在: {TEST_VIDEO}")
    return TEST_VIDEO


@pytest.fixture
def sample_audio() -> Path:
    if not TEST_AUDIO.exists():
        pytest.skip(f"测试音频不存在: {TEST_AUDIO}")
    return TEST_AUDIO


@pytest.fixture
def temp_workspace(tmp_path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def mock_config(tmp_path, monkeypatch) -> Path:
    """临时配置文件，用于测试"""
    cfg_dir = tmp_path / ".config" / "videoscripts"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(
        '{"tencent": {"secret_id": "test_id", "secret_key": "test_key", "region": "ap-guangzhou"}}',
    )
    monkeypatch.setattr(
        "server.config._CONFIG_PATH",
        cfg_path,
    )
    return cfg_path
