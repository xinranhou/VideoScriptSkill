# VideoScriptSkill 需求定义文档 (PRD)

## 1. 核心功能

**功能描述**：输入视频文件、网络 URL 或音频文件，输出带有时间戳段落的转写文字脚本。

**输入格式**：
- 本地视频文件（`.mp4`, `.wav` 等）
- 本地音频文件（`.wav`, `.mp3`, `.m4a` 等）
- 网络视频 URL（B站、YouTube、抖音等，支持 yt-dlp 可识别的平台）

**输出格式**：自动生成 Markdown 格式的文字脚本结果文件，各段落均带有时间戳（如 `[00:00] - [00:59]`）。

## 2. 目标使用场景与使用配置

本项目作为 Skill 提供给 Claude Code、Open Claw 和 Hermes 等工具使用。使用 MCP Server 架构，通过 Claude Code 的 `/transcribe` 命令调用。

### 2.1 转写引擎选择

系统支持两种转写引擎，由用户配置决定：

1. **腾讯云 ASR**：使用腾讯云一句话识别 API，默认引擎 `16k_zh`（中文）
2. **本地 Whisper 引擎**：使用 openai-whisper 进行本地语音识别，支持 Apple Silicon GPU 加速

### 2.2 网络视频下载

- 支持通过 yt-dlp 下载网络视频（B站、YouTube、抖音、小红书、西瓜视频等）
- **实时进度显示**：所有步骤（下载/切片/ASR/校正）均实时输出到终端，每行带 Step 编号（1/5 ~ 5/5），百分比和速度信息，使用 `sys.stderr.flush()` 确保立即可见
- **下载优先级**：
  1. yt-dlp **带 Referer/User-Agent 信息头**优先尝试（使用 `--add-headers` 方式，与命令行一致）
  2. yt-dlp 不带信息头重试（部分 CDN 直链不带 headers 也可下载）
  3. ffmpeg 后备下载（不带信息头，直接下载 CDN 直链）
- 文件大于 100MB 时自动启用断点续传（yt-dlp 的 `continue_dl` 选项）
- 实时向用户推送每一步进度（下载切片、音频转文字、LLM校正）

### 2.3 初始化与配置机制

* **首次加载设置**：检测腾讯云凭证是否配置，引导用户完成配置
* **默认记忆调用**：用户配置保存在 `~/.config/videoscripts/config.json`，后续调用自动使用

## 3. 核心功能详细说明

### 3.1 视频转文字流程

```
1. 输入检测 → 判断本地文件还是网络 URL
2. 下载（如需）→ 网络 URL 自动下载到临时目录，支持断点续传，实时显示下载进度
3. 切片 → ffmpeg 提取音频 + 静音检测 + 能量分析
4. ASR 识别 → 切片后多线程并行调用 ASR（最多 4 线程并发）
5. 合并 → 组装为带时间戳的 Markdown
6. LLM 校正（可选）→ MiniMax M2.7 文本润色，每完成一片实时通知用户进度（单线程顺序处理）
```

### 3.2 智能音频切片

- 使用 ffmpeg `silencedetect` 检测静音点
- 结合 wave 模块能量分析找自然停顿点
- 切片时长控制在 30-59 秒之间
- 切片文件保存在临时工作目录

### 3.3 断点续传 + 处理规则

- 检查点保存在工作目录的 `.checkpoint_*.json` 文件
- 已完成的切片自动跳过，意外中断后可从上次位置继续
- **处理规则**：下载视频可多线程并行；ASR 识别最多 4 线程并发；音频提取文字（Whisper）和文字校正（LLM）需单线程顺序执行，避免内存/资源争抢
- 实时进度显示：同一行原地更新，显示当前步骤（1/5 ~ 5/5）和百分比，不刷屏；stderr 输出后立即 flush 确保实时性

### 3.4 LLM 文本校正

- 使用 MiniMax M2.7 API
- 逐个片段独立校正，每完成一片实时通知用户进度
- 修正同音字错误、专有名词（人名、技术术语）
- 保留时间戳和口语特征
- **中英双语**：如果片段是英文内容，每段先英文原文再输出中文翻译（英文段格式：`## [时间]\n英文原文\n\n中文翻译`，中文段格式：`## [时间]\n中文文本`）

### 3.5 LLM 主题摘要与文件命名

- 转录完成后，使用 LLM 根据内容生成一句话主题摘要（不超过20字）
- 输出文件命名格式：`{作者}_{日期}_{主题}.md` 和 `{作者}_{日期}_{主题}.mp4`
- 作者和日期由用户提供（如未提供则提示）
- 主题由 LLM 根据转录内容自动生成

## 4. 输出格式示例

```markdown
## 处理进度
- Step 1/5: 下载（B站视频URL）
- Step 2/5: 切片处理（静音+能量分析）...
-   共 5 个切片
-   [1/5] OK: 欢迎收看我今天的视频，今天我们来聊一聊关于...
-   [2/5] OK: 上一期我们讲到了这个话题，今天我们来继续深入...
-   [3/5] FAIL: 失败
-   [4/5] OK: 接下来让我给大家演示一下具体操作...
-   [5/5] OK: 最后再补充一点关于这个技术的说明...

---

# 视频转文字脚本

## [00:00] - [00:59]
We just raised $30 million, bringing our total to $40 million at a $500 million valuation.
我们刚刚融资了3000万美元，总融资达到4000万美元，估值5亿美元。

## [00:59] - [01:58]
大家好，我是小俊，今天我们来到了美国硅谷，此刻正在扎克伯格最早的创业所在地 Facebook House...

## [01:58] - [02:32]
We are reimagining infrastructure and introducing new modalities...
我们正在重新构建基础设施，引入新的模态...

---
* 共 5 个切片，成功 5，失败 0 | 引擎：Whisper | 耗时：238.9 秒 | 步骤：1/5下载 2/5切片 3/5ASR 4/5合并 5/5校正 *
```

**说明**：
- 英文片段：先英文原文，再中文翻译（中间空一行分隔）
- 中文片段：直接输出中文文本

## 5. 环境依赖要求

- Python 3.12+（使用 `uv` 管理依赖）
- 系统级依赖：`ffmpeg`（用于音视频剥离和切割）
- Python 依赖：
  - `tencentcloud-sdk-python`（腾讯云 ASR）
  - `openai-whisper`（可选，本地 Whisper 引擎）
  - `yt-dlp`（网络视频下载）
  - `fastmcp`（MCP Server）

## 6. 架构说明

```
用户 (/transcribe URL 或 /path/to/video.mp4)
         │
         ▼
┌──────────────────────────────────┐
│  MCP Server (server/server.py)  │
├──────────────────────────────────┤
│  download.py  - 网络视频下载     │
│  slice.py     - 静音+能量切片   │
│  asr.py       - 腾讯云 ASR 调用  │
│  whisper_asr.py - 本地 Whisper    │
│  correct.py   - LLM 文本校正     │
│  merge.py     - Markdown 合并    │
└──────────────────────────────────┘
         │
         ▼
   腾讯云 ASR / Whisper API + MiniMax API
```

## 7. 错误处理

| 错误类型 | 处理方式 |
|----------|----------|
| 文件不存在 | 提示用户检查路径 |
| 网络 URL 下载失败 | 提示检查 URL 有效性或提供 Cookies |
| ffmpeg 未安装 | 提示运行安装脚本 |
| 腾讯云凭证未配置 | 引导运行 setup_config |
| ASR API 超时 | 重试机制，单片段最多 3 次 |
| LLM 校正超时 | 跳过校正，使用原始文本 |

## 8. 配置文件

凭证存储在 `~/.config/videoscripts/config.json`：

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
