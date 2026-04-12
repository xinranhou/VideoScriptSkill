"""LLM 文本校正模块 — 调用 MiniMax M2.7 校正 ASR 识别错误"""

import json
import logging
import os
import re
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

# None = 未初始化, False = 已确认无 key, str = API key
_api_key: Optional[str] = False  # type: ignore[misc]


def _get_api_key() -> Optional[str]:
    """获取 MiniMax API key，依次检查：环境变量 → 配置文件"""
    global _api_key
    if _api_key is not False:
        return _api_key if _api_key else None

    # 1. 环境变量优先
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if key:
        _api_key = key
        return key

    # 2. 配置文件
    try:
        from .. import config as cfg_mod
        cfg = cfg_mod.load_config()
        key = cfg.get("minimax", {}).get("api_key", "").strip()
        if key:
            _api_key = key
            return key
    except Exception:
        pass

    _api_key = None
    return None


MINIMAX_BASE_URL = "https://api.minimaxi.com"
MINIMAX_MODEL = "MiniMax-M2.7"
SYSTEM_PROMPT = """你是一个专业的视频字幕校正助手。

输入是ASR（语音识别）转录的文本，存在以下常见错误：
- 谐音字错误（如"Transformer"→"贸易架构"，"tokens"→"tos"）
- 专有名词错误（Claude、Llama、OpenAI、Cursor、Figma、MCP等）
- 英文术语错误（API、MCP、CLI、SaaS等）
- 数字和单位错误

你的任务：
1. 修正上述识别错误
2. 将多个片段整合为连贯的段落
3. 保留时间戳标记（## [00:00] - [00:45] 格式）
4. 保留口语特征（语气词、重复等）

输出要求：
- 只输出校正后的Markdown文本
- 不要输出任何分析、解释或说明
- 格式：## [时间]\\n校正后的文本

示例输出格式：
## [00:00] - [00:45]
校正后的第一段文本...

## [00:45] - [01:30]
校正后的第二段文本..."""


def _extract_markdown_content(text: str) -> str:
    """
    从 MiniMax 返回的文本中提取纯 Markdown 内容。
    去除分析说明，只保留 ## [时间] 开头的段落。
    """
    lines = text.split("\n")
    result_lines = []
    in_markdown = False

    for line in lines:
        # 检测 Markdown 段落开始
        if re.match(r"^##?\s*\[\d{2}:\d{2}\]", line.strip()):
            in_markdown = True
            result_lines.append(line)
        elif in_markdown:
            # 如果遇到明显的分析说明标题，停止
            if re.match(r"^\d+\.", line.strip()) or line.strip().startswith("**"):
                # 这可能是分析的一部分，检查是否在 markdown 之后
                break
            result_lines.append(line)

    if result_lines:
        return "\n".join(result_lines).strip()

    # Fallback: 如果没找到 Markdown，尝试找最后一个 ## [时间] 段落
    # 查找所有 ## [时间] 开始的位置
    pattern = r"(## \[?\d{2}:\d{2}[^\n]*\n[\s\S]*)"
    matches = re.findall(pattern, text)
    if matches:
        return matches[-1].strip()

    return text


def correct_text(raw_text: str) -> str:
    """
    调用 MiniMax M2.7 校正 ASR 文本。

    Args:
        raw_text: ASR 原始输出的 Markdown 文本

    Returns:
        校正后的 Markdown 文本。如果无 API key 或调用失败，返回原始文本。
    """
    api_key = _get_api_key()
    if not api_key:
        logger.info("MiniMax API key 未配置，跳过文本校正")
        return raw_text

    payload: dict[str, Any] = {
        "model": MINIMAX_MODEL,
        "thinking": {"type": "off"},
        "messages": [
            {"role": "user", "content": SYSTEM_PROMPT + f"\n\n请校正以下视频转录文本：\n\n{raw_text}"},
        ],
        "max_tokens": 16000,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{MINIMAX_BASE_URL}/anthropic/v1/messages"
    max_retries = 3
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # 检查业务错误
            base_resp = data.get("base_resp", {})
            if base_resp.get("status_code", 0) != 0:
                err_msg = base_resp.get("status_msg", "unknown error")
                raise ValueError(f"MiniMax API error {base_resp.get('status_code')}: {err_msg}")

            # 提取文本内容
            content = data.get("content", [])
            if not content:
                raise ValueError("响应 content 为空")

            # 找 text 块（跳过 thinking）
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        # 提取纯 Markdown 内容
                        markdown = _extract_markdown_content(text)
                        logger.info(f"文本校正完成 ({len(markdown)} 字符)")
                        return markdown

            # 没有 text 块，fallback 取最后一个 block 的文本
            last_block = content[-1]
            fallback = last_block.get("thinking") or last_block.get("text") or ""
            logger.warning(f"响应无 text 块，使用 fallback ({len(fallback)} 字符)")
            return _extract_markdown_content(fallback.strip())

        except Exception as e:
            last_error = str(e)
            is_timeout = isinstance(e, TimeoutError) or "timed out" in last_error.lower() or isinstance(e, urllib.error.HTTPError) and e.code == 504
            logger.warning(f"校正第 {attempt} 次失败: {e}" + (" (超时)" if is_timeout else ""))
            if attempt < max_retries:
                import time
                time.sleep(5 * attempt)

    logger.warning(f"文本校正全部失败: {last_error}，使用原始文本")
    return raw_text
