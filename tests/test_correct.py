"""LLM 校正模块测试"""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestCorrect:
    """测试文本校正逻辑"""

    def test_correct_no_api_key(self, mock_config):
        """无 API key 时返回原始文本"""
        from server.engine import correct

        correct._api_key = False  # 重置缓存
        raw = "# 原始文本\n测试内容"
        result = correct.correct_text(raw)
        assert result == raw

    def test_correct_api_failure_returns_raw(self, mock_config):
        """API 调用抛出异常时返回原始文本"""
        from server.engine import correct

        with patch("urllib.request.urlopen", side_effect=Exception("网络错误")):
            correct._api_key = "fake-key"
            raw = "# 原始\n内容"
            result = correct.correct_text(raw)
            assert result == raw

    def test_correct_api_base_resp_error(self, mock_config):
        """API 返回业务错误时返回原始文本"""
        from server.engine import correct

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "base_resp": {"status_code": 2013, "status_msg": "invalid model"}
        }).encode()

        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            correct._api_key = "fake-key"
            raw = "# 原始\n内容"
            result = correct.correct_text(raw)
            assert result == raw

    def test_correct_api_empty_content(self, mock_config):
        """API 返回空 content 时返回原始文本"""
        from server.engine import correct

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "base_resp": {"status_code": 0, "status_msg": ""},
            "content": []
        }).encode()

        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            correct._api_key = "fake-key"
            raw = "# 原始\n内容"
            result = correct.correct_text(raw)
            assert result == raw

    def test_correct_api_success(self, mock_config):
        """API 调用成功时返回校正文本"""
        from server.engine import correct

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "base_resp": {"status_code": 0, "status_msg": ""},
            "content": [
                {"type": "thinking", "thinking": "思考中..."},
                {"type": "text", "text": "# 校正后\n修正内容"}
            ]
        }).encode()

        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            correct._api_key = "fake-key"
            raw = "# 原始\n内容"
            result = correct.correct_text(raw)
            assert result == "# 校正后\n修正内容"

    def test_correct_api_no_text_block(self, mock_config):
        """API 返回无 text 块时 fallback 到最后 block"""
        from server.engine import correct

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "base_resp": {"status_code": 0, "status_msg": ""},
            "content": [
                {"type": "thinking", "thinking": "思考中..."}
            ]
        }).encode()

        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            correct._api_key = "fake-key"
            raw = "# 原始\n内容"
            result = correct.correct_text(raw)
            assert result == "思考中..."

    def test_correct_uses_minimax_endpoint(self, mock_config):
        """验证调用了正确的 MiniMax 端点"""
        from server.engine import correct

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "base_resp": {"status_code": 0},
            "content": [{"type": "text", "text": "result"}]
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        called_url = []

        def capture_urlopen(req, **kwargs):
            called_url.append(req.full_url)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            correct._api_key = "fake-key"
            correct.correct_text("# raw")

        assert called_url[0] == "https://api.minimaxi.com/anthropic/v1/messages"
