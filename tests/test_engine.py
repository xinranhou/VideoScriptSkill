"""核心引擎单元测试"""

import pytest
from pathlib import Path
import json
import tempfile
import shutil

from server.engine import merge
from server.engine.merge import fmt_timestamp, merge_to_markdown, Segment


class TestMerge:
    """测试结果合并逻辑"""

    def test_fmt_timestamp(self):
        assert fmt_timestamp(0) == "00:00"
        assert fmt_timestamp(45) == "00:45"
        assert fmt_timestamp(60) == "01:00"
        assert fmt_timestamp(90) == "01:30"
        assert fmt_timestamp(3661) == "61:01"

    def test_merge_to_markdown_single_success(self, tmp_path):
        from server.engine.slice import Chunk

        chunks = [
            Chunk(index=0, start_sec=0, end_sec=45, path=tmp_path / "c_0_45.wav"),
        ]
        results = {0: "这是第一段识别文本"}

        md = merge_to_markdown(chunks, results)

        assert "# 视频转文字脚本" in md
        assert "## [00:00] - [00:45]" in md
        assert "这是第一段识别文本" in md
        assert "成功 1，失败 0" in md

    def test_merge_to_markdown_with_failure(self, tmp_path):
        from server.engine.slice import Chunk

        chunks = [
            Chunk(index=0, start_sec=0, end_sec=45, path=tmp_path / "c_0_45.wav"),
            Chunk(index=1, start_sec=45, end_sec=90, path=tmp_path / "c_45_90.wav"),
        ]
        results = {0: "第一段文字", 1: None}

        md = merge_to_markdown(chunks, results)

        assert "成功 1，失败 1" in md
        assert "此片段识别失败" in md

    def test_merge_to_markdown_empty_result(self, tmp_path):
        from server.engine.slice import Chunk

        chunks = [
            Chunk(index=0, start_sec=0, end_sec=45, path=tmp_path / "c_0_45.wav"),
        ]
        results = {0: None}

        md = merge_to_markdown(chunks, results)
        assert "失败 1" in md


class TestConfig:
    """测试配置读写"""

    def test_load_config_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "server.config._CONFIG_PATH",
            tmp_path / "nonexistent.json",
        )
        from server import config
        cfg = config.load_config()
        assert cfg == {}

    def test_save_and_load_config(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        monkeypatch.setattr("server.config._CONFIG_PATH", cfg_path)

        from server import config
        test_cfg = {"tencent": {"secret_id": "abc", "secret_key": "xyz"}}
        config.save_config(test_cfg)
        loaded = config.load_config()

        assert loaded["tencent"]["secret_id"] == "abc"
        assert loaded["tencent"]["secret_key"] == "xyz"

    def test_get_tencent_creds_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "server.config._CONFIG_PATH",
            tmp_path / "empty.json",
        )
        # 写入空配置
        tmp_path.joinpath("empty.json").write_text("{}")

        from server import config
        with pytest.raises(ValueError, match="腾讯云凭证未配置"):
            config.get_tencent_creds()

    def test_get_tencent_creds_ok(self, mock_config):
        from server import config
        creds = config.get_tencent_creds()
        assert creds["secret_id"] == "test_id"
        assert creds["secret_key"] == "test_key"
        assert creds["region"] == "ap-guangzhou"


class TestSlice:
    """测试切片逻辑（不依赖 ffmpeg 的部分）"""

    def test_prepare_chunks_unsupported_format(self, tmp_path):
        from server.engine import slice as slice_mod

        fake_video = tmp_path / "video.avi"
        fake_video.write_bytes(b"fake")

        with pytest.raises(ValueError, match="不支持的视频格式"):
            slice_mod.prepare_chunks(fake_video, tmp_path)

    def test_prepare_chunks_wav_not_found(self):
        from server.engine import slice as slice_mod

        with pytest.raises(FileNotFoundError):
            slice_mod.prepare_chunks("/nonexistent/file.wav")


class TestEngine:
    """测试核心引擎入口"""

    def test_transcribe_file_not_found(self):
        from server.engine import engine

        with pytest.raises(FileNotFoundError):
            engine.transcribe("/nonexistent/video.mp4")

    def test_transcribe_invalid_chunk_duration(self, sample_audio):
        from server.engine import engine

        with pytest.raises(ValueError, match="chunk_duration 必须在"):
            engine.transcribe(str(sample_audio), chunk_duration=100)

        with pytest.raises(ValueError, match="chunk_duration 必须在"):
            engine.transcribe(str(sample_audio), chunk_duration=20)
