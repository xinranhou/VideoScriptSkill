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

SYSTEM_PROMPT_NO_TRANS = """你是一个专业的视频字幕校正助手。

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
5. **重要**：如果内容是英文，每段先英文原文再输出中文翻译，中间空一行分隔
6. 如果内容是中文，直接输出中文文本，不需要翻译

输出要求：
- 只输出校正后的Markdown文本
- 不要输出任何分析、解释或说明
- 英文段格式：## [时间]\n英文原文\n\n中文翻译
- 中文段格式：## [时间]\n中文文本
- 每个时间戳段落必须包含内容，不能为空

示例输出格式（英文段）：
## [00:00] - [00:45]
We just raised $30 million...
我们刚刚融资了3000万美元...

示例输出格式（中文段）：
## [00:45] - [01:30]
欢迎收看我今天的视频，今天我们来聊一聊..."""

SYSTEM_PROMPT_WITH_TRANS = """你是一个专业的视频字幕校正助手。

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
5. **重要**：如果内容是英文，每段先英文原文再输出中文翻译，中间空一行分隔
6. 如果内容是中文，直接输出中文文本，不需要翻译

输出要求：
- 只输出校正后的Markdown文本
- 不要输出任何分析、解释或说明
- 英文段格式：## [时间]\n英文原文\n\n中文翻译
- 中文段格式：## [时间]\n中文文本
- 每个时间戳段落必须包含内容，不能为空

示例输出格式（英文段）：
## [00:00] - [00:45]
We just raised $30 million...

我们刚刚融资了3000万美元...

示例输出格式（中文段）：
## [00:45] - [01:30]
欢迎收看我今天的视频，今天我们来聊一聊..."""


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


def _correct_chunk(chunk_text: str, api_key: str, enable_translation: bool = False) -> str:
    """
    校正单个文本片段。
    enable_translation=True 时输出原文+中文翻译，False 时只输出原文。
    """
    system_prompt = SYSTEM_PROMPT_WITH_TRANS if enable_translation else SYSTEM_PROMPT_NO_TRANS
    payload: dict[str, Any] = {
        "model": MINIMAX_MODEL,
        "thinking": {"type": "off"},
        "messages": [
            {"role": "user", "content": system_prompt + f"\n\n请校正以下视频转录文本：\n\n{chunk_text}"},
        ],
        "max_tokens": 8000,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = f"{MINIMAX_BASE_URL}/anthropic/v1/messages"

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            base_resp = data.get("base_resp", {})
            if base_resp.get("status_code", 0) != 0:
                raise ValueError(f"MiniMax API error {base_resp.get('status_code')}: {base_resp.get('status_msg', 'unknown')}")

            content = data.get("content", [])
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        return _extract_markdown_content(text)

            # fallback
            last_block = content[-1]
            fallback = last_block.get("thinking") or last_block.get("text") or ""
            return _extract_markdown_content(fallback.strip())

        except Exception as e:
            if attempt < 3:
                import time
                time.sleep(3 * attempt)
            else:
                raise e

    raise RuntimeError("校正失败")


def _split_into_chunks(text: str) -> list[tuple[str, str]]:
    """
    将文本按时间戳分割成多个片段。
    返回 [(timestamp, content), ...]
    """
    segments = []
    # 按 ## [00:00] - [00:59] 分割
    pattern = r"(## \[\d{2}:\d{2}\] - \[\d{2}:\d{2}\])\n(.*?)(?=(## \[|$))"
    matches = re.findall(pattern, text, re.DOTALL)
    for match in matches:
        timestamp = match[0]
        content = match[1].strip()
        segments.append((timestamp, content))
    return segments


def correct_text(raw_text: str, progress_callback=None, enable_translation: bool = False) -> str:
    """
    调用 MiniMax M2.7 校正 ASR 文本。支持分段处理和进度回调。
    每段独立校正，如果某段内容为空或失败则保留原始文本。

    Args:
        raw_text: ASR 原始输出的 Markdown 文本
        progress_callback: 进度回调函数，第一个参数为当前片段index，第二个为总片段数
        enable_translation: 是否启用翻译为中文（默认 False）

    Returns:
        校正后的 Markdown 文本。如果无 API key 或调用失败，返回原始文本。
    """
    api_key = _get_api_key()
    if not api_key:
        logger.info("MiniMax API key 未配置，跳过文本校正")
        return raw_text

    mode_label = "翻译" if enable_translation else "校正"
    segments = _split_into_chunks(raw_text)
    if not segments:
        return _correct_chunk(raw_text, api_key, enable_translation)

    total = len(segments)
    import sys
    print(f"\r[Step 5/5 LLM{mode_label}] 开始... 共{total}个片段", file=sys.stderr, flush=True)

    corrected_segments = []
    for i, (timestamp, content) in enumerate(segments):
        percent = int((i + 1) * 100 / total)
        print(f"\r[Step 5/5 LLM{mode_label}] {percent}% [{i+1}/{total}]", end="", file=sys.stderr, flush=True)

        if not content or not content.strip():
            corrected_segments.append((timestamp, content))
            print(f"[{mode_label}] 片段 {i+1} 为空，跳过")
            continue

        try:
            corrected = _correct_chunk(f"{timestamp}\n{content}", api_key, enable_translation)
            corrected_content = _extract_content_from_corrected(corrected, timestamp)

            if not corrected_content or not corrected_content.strip():
                print(f"[{mode_label}] 片段 {i+1} 解析为空，使用原始文本")
                corrected_segments.append((timestamp, content))
            else:
                corrected_segments.append((timestamp, corrected_content))
        except Exception as e:
            print(f"[{mode_label}] 片段 {i+1} 失败: {e}，使用原始文本")
            corrected_segments.append((timestamp, content))

    result_lines = []
    for timestamp, content in corrected_segments:
        result_lines.append(timestamp)
        if content:
            result_lines.append(content)
        result_lines.append("")

    return "\n".join(result_lines).strip()


def _extract_content_from_corrected(corrected_text: str, expected_timestamp: str) -> str:
    """
    从 LLM 校正结果中提取纯内容。
    处理两种格式：
    - 英文段：## [时间]\n英文原文\n\n中文翻译
    - 中文段：## [时间]\n中文文本

    Returns:
        提取的内容字符串（不含时间戳）
    """
    # 检查是否为空
    if not corrected_text or not corrected_text.strip():
        return ""

    lines = corrected_text.split("\n")
    content_lines = []
    found_timestamp = False
    past_timestamps = False

    for line in lines:
        # 检测时间戳行
        timestamp_match = re.match(r"^##?\s*\[\d{2}:\d{2}\]", line.strip())
        if timestamp_match:
            if found_timestamp and past_timestamps:
                # 遇到第二个时间戳，停止
                break
            found_timestamp = True
            past_timestamps = True
            continue
        content_lines.append(line)

    result = "\n".join(content_lines).strip()
    return result
