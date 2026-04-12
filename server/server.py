#!/usr/bin/env python3
"""
VideoScriptSkill MCP Server

Usage:
    # 开发调试
    python server/server.py

    # 安装到 Claude Code
    uv run mcp install server/server.py
    # 或者
    fastmcp install server/server.py
"""

import logging
import sys
from pathlib import Path

# 添加项目根目录到 sys.path，确保可以 import server
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from server.engine import engine
from server.config import get_config_path, load_config, save_config, ensure_config_dir

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# MCP Server 实例
app = Server("videoscripts")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """列出 MCP Server 提供的所有工具"""
    return [
        Tool(
            name="transcribe_video",
            description=(
                "将 mp4 视频文件或 wav 音频文件转录为带时间定位的文字脚本。"
                "使用腾讯云 ASR，输出 Markdown 格式。"
                "自动将视频按静音点+能量分析切分为 30-59 秒的自然片段，单线程处理。"
                "可选调用 MiniMax M2.7 进行文本校正（修正谐音错误、专有名词等）。"
                "校正结果自动保存到视频同目录下的 _transcript.md 文件。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {
                        "type": "string",
                        "description": "视频或音频文件路径（支持 mp4、wav）",
                    },
                    "chunk_duration": {
                        "type": "integer",
                        "description": "切片时长（秒），默认 45，必须在 30-59 之间",
                        "default": 45,
                        "minimum": 30,
                        "maximum": 59,
                    },
                    "enable_correction": {
                        "type": "boolean",
                        "description": "是否启用 LLM 文本校正（需要 MiniMax API Key），默认 true",
                        "default": True,
                    },
                    "output_path": {
                        "type": "string",
                        "description": "输出文件路径，默认保存到视频同目录下",
                    },
                },
                "required": ["video_path"],
            },
        ),
        Tool(
            name="check_config",
            description="检查腾讯云凭证和 ffmpeg 是否已正确配置",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="setup_config",
            description="配置腾讯云 SecretId/SecretKey 和 MiniMax API Key",
            inputSchema={
                "type": "object",
                "properties": {
                    "secret_id": {"type": "string", "description": "腾讯云 SecretId"},
                    "secret_key": {"type": "string", "description": "腾讯云 SecretKey"},
                    "region": {
                        "type": "string",
                        "description": "腾讯云地域，默认 ap-guangzhou",
                        "default": "ap-guangzhou",
                    },
                    "minimax_api_key": {
                        "type": "string",
                        "description": "MiniMax API Key（用于文本校正，启用 LLM 校正时必需）",
                    },
                },
                "required": ["secret_id", "secret_key"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """处理工具调用"""
    if name == "transcribe_video":
        return await _transcribe_video(arguments)
    elif name == "check_config":
        return await _check_config(arguments)
    elif name == "setup_config":
        return await _setup_config(arguments)
    else:
        raise ValueError(f"未知工具: {name}")


async def _transcribe_video(args: dict) -> list[TextContent]:
    video_path: str = args["video_path"]
    chunk_duration: int = args.get("chunk_duration", 45)
    enable_correction: bool = args.get("enable_correction", True)
    output_path: str | None = args.get("output_path")

    try:
        markdown = engine.transcribe(
            video_path,
            chunk_duration=chunk_duration,
            enable_correction=enable_correction,
            output_path=output_path,
        )
        return [TextContent(type="text", text=markdown)]
    except FileNotFoundError as e:
        return [TextContent(type="text", text=f"错误: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"配置错误: {e}")]
    except Exception as e:
        logger.exception("转录失败")
        return [TextContent(type="text", text=f"转录失败: {e}")]


async def _check_config(_args: dict) -> list[TextContent]:
    from server.engine.slice import check_ffmpeg
    from server.config import get_tencent_creds, get_minimax_key

    lines = []

    # 检查 ffmpeg
    if check_ffmpeg():
        lines.append("✅ ffmpeg 已安装")
    else:
        lines.append("❌ ffmpeg 未安装，请先运行 scripts/install.sh")

    # 检查腾讯云凭证
    try:
        creds = get_tencent_creds()
        lines.append(f"✅ 腾讯云凭证已配置 (region: {creds['region']})")
    except ValueError as e:
        lines.append(f"❌ {e}")

    # 检查 MiniMax
    minimax_key = get_minimax_key()
    if minimax_key:
        lines.append(f"✅ MiniMax API Key 已配置")
    else:
        lines.append("⚠️  MiniMax API Key 未配置（文本校正将被跳过）")

    return [TextContent(type="text", text="\n".join(lines))]


async def _setup_config(args: dict) -> list[TextContent]:
    secret_id: str = args["secret_id"]
    secret_key: str = args["secret_key"]
    region: str = args.get("region", "ap-guangzhou")
    minimax_key: str = args.get("minimax_api_key", "")

    if not secret_id or not secret_key:
        return [TextContent(type="text", text="❌ secret_id 和 secret_key 不能为空")]

    config = load_config()
    config.setdefault("tencent", {})
    config["tencent"]["secret_id"] = secret_id
    config["tencent"]["secret_key"] = secret_key
    config["tencent"]["region"] = region
    if minimax_key:
        config.setdefault("minimax", {})
        config["minimax"]["api_key"] = minimax_key
    save_config(config)

    cfg_path = get_config_path()
    msg = f"✅ 凭证已保存到 {cfg_path}"
    if minimax_key:
        msg += "\n✅ MiniMax API Key 已保存"
    return [TextContent(type="text", text=msg)]


async def main():
    """MCP Server 主入口"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
