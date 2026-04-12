"""腾讯云 ASR Mock 测试 — 模拟 API 响应"""

import pytest
import responses


class TestASRMock:
    """使用 responses 库模拟腾讯云 ASR API"""

    @responses.activate
    def test_recognize_success(self, mock_config, tmp_path):
        responses.add(
            responses.POST,
            "https://asr.ap-guangzhou.tencentcloudapi.com",
            json={
                "Response": {
                    "Result": "这是测试识别的文本内容",
                    "RequestId": "test-request-id",
                }
            },
            status=200,
        )

        from server.engine import asr
        from server.engine.slice import Chunk

        chunk_path = tmp_path / "test.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 100 + b"WAVE")

        chunks = [Chunk(index=0, start_sec=0, end_sec=45, path=chunk_path)]
        results = asr.recognize_all(chunks)

        assert results[0] == "这是测试识别的文本内容"
        assert len(responses.calls) == 1

    @responses.activate
    def test_recognize_retry_then_success(self, mock_config, tmp_path):
        """首次失败，第二次重试成功"""
        responses.add(
            responses.POST,
            "https://asr.ap-guangzhou.tencentcloudapi.com",
            json={"Response": {"Error": {"Code": "InternalError", "Message": "temp"}}},
            status=500,
        )
        responses.add(
            responses.POST,
            "https://asr.ap-guangzhou.tencentcloudapi.com",
            json={
                "Response": {
                    "Result": "重试后成功的文本",
                    "RequestId": "test-request-id-2",
                }
            },
            status=200,
        )

        from server.engine import asr
        from server.engine.slice import Chunk

        chunk_path = tmp_path / "test2.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 100 + b"WAVE")

        chunks = [Chunk(index=0, start_sec=0, end_sec=45, path=chunk_path)]
        results = asr.recognize_all(chunks)

        assert results[0] == "重试后成功的文本"
        assert len(responses.calls) == 2

    @responses.activate
    def test_recognize_all_fail_after_retries(self, mock_config, tmp_path):
        """所有重试都失败"""
        for _ in range(3):
            responses.add(
                responses.POST,
                "https://asr.ap-guangzhou.tencentcloudapi.com",
                json={"Response": {"Error": {"Code": "InternalError"}}},
                status=500,
            )

        from server.engine import asr
        from server.engine.slice import Chunk

        chunk_path = tmp_path / "test3.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 100 + b"WAVE")

        chunks = [Chunk(index=0, start_sec=0, end_sec=45, path=chunk_path)]
        results = asr.recognize_all(chunks)

        assert results[0] is None
        assert len(responses.calls) == 3

    @responses.activate
    def test_recognize_multiple_chunks(self, mock_config, tmp_path):
        """多个切片的顺序处理"""
        for i in range(3):
            responses.add(
                responses.POST,
                "https://asr.ap-guangzhou.tencentcloudapi.com",
                json={
                    "Response": {
                        "Result": f"第 {i + 1} 段文本内容",
                        "RequestId": f"req-{i}",
                    }
                },
                status=200,
            )

        from server.engine import asr
        from server.engine.slice import Chunk

        chunks = []
        for i in range(3):
            p = tmp_path / f"chunk_{i}.wav"
            p.write_bytes(b"RIFF" + b"\x00" * 50 + b"WAVE")
            chunks.append(Chunk(index=i, start_sec=i * 45, end_sec=(i + 1) * 45, path=p))

        results = asr.recognize_all(chunks)

        for i in range(3):
            assert results[i] == f"第 {i + 1} 段文本内容"
        assert len(responses.calls) == 3

    @responses.activate
    def test_progress_callback_called(self, mock_config, tmp_path):
        """验证进度回调被正确调用"""
        responses.add(
            responses.POST,
            "https://asr.ap-guangzhou.tencentcloudapi.com",
            json={"Response": {"Result": "文本"}},
            status=200,
        )

        from server.engine import asr
        from server.engine.slice import Chunk

        chunk_path = tmp_path / "test.wav"
        chunk_path.write_bytes(b"RIFF" + b"\x00" * 50 + b"WAVE")

        chunks = [Chunk(index=0, start_sec=0, end_sec=45, path=chunk_path)]
        calls = []

        def progress(idx, total, result, chunk):
            calls.append((idx, total, result))

        asr.recognize_all(chunks, progress_callback=progress)

        assert len(calls) == 1
        assert calls[0] == (1, 1, "文本")
