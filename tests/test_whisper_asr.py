"""Whisper ASR Mock 测试 — 模拟 Whisper 模型识别"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# 先导入 whisper_asr 模块（不会触发 whisper 加载）
import server.engine.whisper_asr as whisper_asr_module


class TestWhisperASR:
    """Whisper ASR 模块测试"""

    def test_recognize_chunk_success(self, mock_config, tmp_path):
        """单个片段识别成功"""
        from server.engine.slice import Chunk

        chunk_path = tmp_path / "test.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 100 + b"WAVE")

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "这是 Whisper 识别的文本"}

        with patch.object(whisper_asr_module, "_load_whisper", return_value=mock_model):
            whisper_asr_module._whisper_model = mock_model
            result = whisper_asr_module.recognize_chunk(chunk_path, 1)

        assert result == "这是 Whisper 识别的文本"

    def test_recognize_chunk_failure(self, mock_config, tmp_path):
        """识别失败返回 None"""
        chunk_path = tmp_path / "test.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 100 + b"WAVE")

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("识别失败")

        with patch.object(whisper_asr_module, "_load_whisper", return_value=mock_model):
            whisper_asr_module._whisper_model = mock_model
            result = whisper_asr_module.recognize_chunk(chunk_path, 1)

        assert result is None

    def test_recognize_all_multiple_chunks(self, mock_config, tmp_path):
        """多个切片顺序识别"""
        from server.engine.slice import Chunk

        chunks = []
        for i in range(3):
            p = tmp_path / f"chunk_{i}.wav"
            p.write_bytes(b"RIFF" + b"\x00" * 50 + b"WAVE")
            chunks.append(Chunk(index=i, start_sec=i * 45, end_sec=(i + 1) * 45, path=p))

        mock_model = MagicMock()
        mock_model.transcribe.side_effect = [
            {"text": f"第 {i + 1} 段文本"} for i in range(3)
        ]

        with patch.object(whisper_asr_module, "_load_whisper", return_value=mock_model):
            whisper_asr_module._whisper_model = mock_model
            results = whisper_asr_module.recognize_all(chunks)

        for i in range(3):
            assert results[i] == f"第 {i + 1} 段文本"

    def test_progress_callback_called(self, mock_config, tmp_path):
        """验证进度回调被正确调用"""
        from server.engine.slice import Chunk

        chunk_path = tmp_path / "test.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 50 + b"WAVE")

        chunks = [Chunk(index=0, start_sec=0, end_sec=45, path=chunk_path)]
        calls = []

        def progress(idx, total, result, chunk):
            calls.append((idx, total, result))

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "识别的文本"}

        with patch.object(whisper_asr_module, "_load_whisper", return_value=mock_model):
            whisper_asr_module._whisper_model = mock_model
            whisper_asr_module.recognize_all(chunks, progress_callback=progress)

        assert len(calls) == 1
        assert calls[0] == (1, 1, "识别的文本")

    def test_is_available_returns_true(self, mock_config):
        """is_available 返回 True 当模型可用"""
        mock_model = MagicMock()
        with patch.object(whisper_asr_module, "_load_whisper", return_value=mock_model):
            whisper_asr_module._whisper_model = mock_model
            assert whisper_asr_module.is_available() is True

    def test_is_available_returns_false_when_load_fails(self, mock_config):
        """is_available 返回 False 当模型加载失败"""
        with patch.object(whisper_asr_module, "_load_whisper", return_value=None):
            whisper_asr_module._whisper_model = None
            assert whisper_asr_module.is_available() is False

    def test_whisper_engine_in_engine_module(self, mock_config, tmp_path):
        """验证 Whisper 引擎可以通过 engine 模块调用"""
        from server.engine.slice import Chunk

        chunks = [
            Chunk(index=0, start_sec=0, end_sec=45, path=tmp_path / "c.wav"),
        ]
        (tmp_path / "c.wav").write_bytes(b"RIFF" + b"\x00" * 50 + b"WAVE")

        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "引擎测试文本"}

        with patch.object(whisper_asr_module, "_load_whisper", return_value=mock_model):
            whisper_asr_module._whisper_model = mock_model
            from server.engine import engine

            results = engine._recognize_whisper_with_checkpoint(
                chunks, {}, tmp_path / "checkpoint.json"
            )

        assert results[0] == "引擎测试文本"

    def test_recognize_chunk_when_whisper_unavailable(self, mock_config, tmp_path):
        """Whisper 不可用时 recognize_chunk 返回 None"""
        chunk_path = tmp_path / "test.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 100 + b"WAVE")

        with patch.object(whisper_asr_module, "_load_whisper", return_value=None):
            whisper_asr_module._whisper_model = None
            result = whisper_asr_module.recognize_chunk(chunk_path, 1)

        assert result is None
