# VideoScriptSkill

将 mp4 视频、wav 音频或网络视频 URL 转录为带时间定位的 Markdown 文字脚本。支持断点续传，腾讯云 ASR 驱动。

## 功能特性

- **多格式支持**：输入 mp4 视频、wav 音频或网络 URL（B站、YouTube、抖音等）
- **网络视频下载**：支持通过 yt-dlp 下载 B站、YouTube、抖音、小红书、西瓜视频等，CDN 直链不加信息头直接下载
- **智能切片**：静音检测 + 能量分析双保险，优先在自然停顿点切割
- **断点续传**：意外中断后可从上次位置继续
- **时间定位**：每个片段精确到 MM:SS 时间戳
- **单线程处理**：切片后逐个处理，每完成一片实时通知用户进度
- **Markdown 输出**：结构清晰，便于阅读和二次编辑
- **LLM 文本校正**：可选调用 MiniMax M2.7 修正谐音错误、专有名词、术语（需要 MiniMax API Key）
- **自动保存**：转录结果自动保存到视频同目录下的 `_transcript.md` 文件
- **实时进度**：每个处理步骤实时展示当前进度

## 架构

```
用户 (/transcribe URL 或 /path/to/video.mp4)
         │
         ▼
┌──────────────────────────────────┐
│  MCP Server (server/server.py)   │ ← 底层执行引擎
│  ├─ download.py  网络视频下载      │
│  ├─ slice.py     静音+能量切片    │
│  ├─ asr.py       腾讯云 ASR 调用   │
│  ├─ whisper_asr.py 本地 Whisper    │
│  ├─ correct.py   LLM 文本校正     │
│  └─ merge.py     合并为 Markdown  │
└──────────────────────────────────┘
         │
         ▼
   腾讯云 ASR / Whisper API
```

## 前置要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) 包管理器
- [ffmpeg](https://ffmpeg.org/)（视频切片用）
- 腾讯云 ASR 服务（需开通[一句话识别](https://cloud.tencent.com/product/asr)）

## 安装

### 1. 一键安装（推荐）

```bash
cd VideoScriptSkill
chmod +x scripts/install.sh
./scripts/install.sh
```

安装向导会：
- 检查并安装依赖（uv、ffmpeg）
- 引导输入腾讯云凭证
- 测试 API 连通性
- 注册 MCP Server

### 2. 手动安装

```bash
# 安装依赖
uv sync

# 配置腾讯云凭证
mkdir -p ~/.config/videoscripts/
cp config.example.json ~/.config/videoscripts/config.json
# 编辑 config.json，填入你的 SecretId 和 SecretKey

# 注册 MCP Server
uv run mcp install server/server.py
```

## 使用方式

### 在 Claude Code 中

支持本地文件和网络 URL：

```
/transcribe https://www.bilibili.com/video/BV1xx411c7XD
/transcribe /path/to/video.mp4
```

或更详细的命令：

```
/transcribe https://www.bilibili.com/video/BV1xx411c7XD --chunk-duration 45
```

### 通过 MCP Tool

Claude Code 安装 MCP Server 后，可直接调用工具：

```json
{
  "name": "download_video",
  "arguments": {
    "url": "https://www.bilibili.com/video/BV1xx411c7XD",
    "quality": "1080p"
  }
}
```

```json
{
  "name": "transcribe_video",
  "arguments": {
    "video_path": "https://www.bilibili.com/video/BV1xx411c7XD",
    "chunk_duration": 45
  }
}
```

**支持的视频平台**：B站、YouTube、抖音、小红书、西瓜视频等主流平台

### 检查配置

```bash
uv run python -c "
import sys; sys.path.insert(0, 'server')
from server.server import app
# 调用 check_config tool
"
```

## 配置说明

凭证保存在 `~/.config/videoscripts/config.json`：

```json
{
  "tencent": {
    "secret_id": "YOUR_SECRET_ID",
    "secret_key": "YOUR_SECRET_KEY",
    "region": "ap-guangzhou"
  },
  "minimax": {
    "api_key": "YOUR_MINIMAX_API_KEY"
  },
  "asr": {
    "engine": "16k_zh",
    "chunk_duration": 45,
    "max_retries": 3,
    "batch_sleep_seconds": 2,
    "batch_size": 10
  },
  "slicing": {
    "min_silence_len": 0.4,
    "silence_thresh": -42,
    "max_offset": 2.0,
    "min_pause_sec": 0.5
  }
}
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `engine` | ASR 引擎 | `16k_zh`（中文）|
| `chunk_duration` | 切片时长（秒） | `45` |
| `max_retries` | 单片段最大重试次数 | `3` |
| `batch_sleep_seconds` | 每 10 片段强制休眠（秒） | `2` |

引擎选项：
- `16k_zh` — 中文
- `16k_en` — 英文
- `16k_zh-TW` — 粤语

## 输出示例

```markdown
# 视频转文字脚本

## [00:00] - [00:45]
欢迎收看我今天的视频，今天我们来聊一聊关于...

## [00:45] - [01:30]
上一期我们讲到了这个话题，今天我们来继续深入...

## [01:30] - [02:15]
接下来让我给大家演示一下具体操作...

---
*共 5 个切片，成功 4，失败 1*
```

## 测试

```bash
uv sync --all-extras
uv run pytest tests/ -v
```

## 项目结构

```
VideoScriptSkill/
├── README.md               # 本文件
├── INSTALL.md              # 安装指南
├── LICENSE                 # MIT
├── pyproject.toml         # Python 项目配置
├── config.example.json    # 配置示例
├── .mcp.json              # MCP Server 配置
├── .gitignore
│
├── server/                # MCP Server
│   ├── server.py          # MCP 入口
│   ├── config.py          # 配置读写
│   └── engine/
│       ├── engine.py       # 主入口
│       ├── download.py      # 网络视频下载（yt-dlp）
│       ├── slice.py        # 视频切片
│       ├── asr.py          # 腾讯云 ASR
│       ├── whisper_asr.py  # 本地 Whisper ASR
│       ├── correct.py      # MiniMax LLM 文本校正
│       └── merge.py        # Markdown 合并
│
├── scripts/
│   └── install.sh         # 安装脚本
│
└── tests/
    ├── conftest.py
    ├── test_engine.py
    ├── test_asr_mock.py
    └── test_correct.py
```

## 常见问题

**Q: 提示 "ffmpeg 未安装"**
```bash
# macOS
brew install ffmpeg
# Ubuntu/Debian
sudo apt install ffmpeg
# Windows
winget install ffmpeg
```

**Q: ASR 识别失败率较高**
- 检查音频是否清晰
- 尝试缩短 `chunk_duration` 到 30 秒
- 确认使用的是正确的 `engine`（中文用 `16k_zh`，英文用 `16k_en`）

**Q: 如何提高识别质量？**
- 提供高质量音频（16kHz、单声道、WAV 格式）
- 避免背景音乐或噪音
- 说话清晰、语速适中

## License

MIT
