#!/usr/bin/env bash
#
# VideoScriptSkill 安装脚本
# 功能：检查依赖、引导配置、测试连通性、注册 MCP Server
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CONFIG_PATH="${HOME}/.config/videoscripts/config.json"
MCP_COMMAND="uv run python ${PROJECT_ROOT}/server/server.py"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; }
confirm() { echo -n "$1 "; read -r REPLY; }

echo "======================================"
echo "  VideoScriptSkill 安装向导"
echo "======================================"
echo ""

# ============================================================================
# 1. 检查 uv
# ============================================================================
info "检查 uv..."
if ! command -v uv &> /dev/null; then
    error "未找到 uv。请先安装: https://github.com/astral-sh/uv"
    exit 1
fi
info "uv 已安装: $(uv --version)"

# ============================================================================
# 2. 安装 Python 依赖
# ============================================================================
info "安装 Python 依赖..."
cd "$PROJECT_ROOT"
uv sync
info "依赖安装完成"

# ============================================================================
# 3. 检查 ffmpeg
# ============================================================================
info "检查 ffmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    error "未找到 ffmpeg。"
    echo ""
    echo "请安装 ffmpeg："
    echo "  macOS:  brew install ffmpeg"
    echo "  Ubuntu/Debian:  sudo apt install ffmpeg"
    echo "  Windows:  winget install ffmpeg (或从 https://ffmpeg.org 下载)"
    exit 1
fi
info "ffmpeg 已安装: $(ffmpeg -version 2>&1 | head -1)"

if ! command -v ffprobe &> /dev/null; then
    warn "未找到 ffprobe，部分功能可能受限"
fi

# ============================================================================
# 4. 引导配置腾讯云凭证
# ============================================================================
echo ""
info "腾讯云 ASR 凭证配置"
echo "（凭证将保存到 ${CONFIG_PATH}）"
echo ""

# 检查是否已有配置
if [ -f "$CONFIG_PATH" ]; then
    confirm "发现已有配置，是否重新配置？(y/N)"
    if [ "$REPLY" != "y" ] && [ "$REPLY" != "Y" ]; then
        info "使用现有配置"
    else
        SKIP_CONFIG=false
    fi
else
    SKIP_CONFIG=false
fi

if [ "${SKIP_CONFIG:-true}" = false ] || [ ! -f "$CONFIG_PATH" ]; then
    mkdir -p "$(dirname "$CONFIG_PATH")"

    echo -n "请输入腾讯云 SecretId: "
    read -r SECRET_ID

    echo -n "请输入腾讯云 SecretKey: "
    read -r SECRET_KEY

    REGION_DEFAULT="ap-guangzhou"
    echo -n "请输入地域 [${REGION_DEFAULT}]: "
    read -r REGION
    REGION="${REGION:-${REGION_DEFAULT}}"

    # MiniMax API Key（可选）
    echo -n "请输入 MiniMax API Key（用于文本校正，可跳过）: "
    read -r MINIMAX_KEY

    if [ -z "$SECRET_ID" ] || [ -z "$SECRET_KEY" ]; then
        error "SecretId 和 SecretKey 不能为空"
        exit 1
    fi

    # 组装 minimax 配置
    if [ -n "$MINIMAX_KEY" ]; then
        MINIMAX_JSON="\"minimax\": {\"api_key\": \"${MINIMAX_KEY}\"},"
    else
        MINIMAX_JSON=""
    fi

    # 写入配置
    cat > "$CONFIG_PATH" << EOF
{
  "tencent": {
    "secret_id": "${SECRET_ID}",
    "secret_key": "${SECRET_KEY}",
    "region": "${REGION}"
  },
  ${MINIMAX_JSON}
  "asr": {
    "engine": "16k_zh",
    "voice_format": "wav",
    "sample_rate": 16000,
    "chunk_duration": 45,
    "max_retries": 3,
    "retry_base_delay": 3,
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
EOF
    info "配置已保存到 ${CONFIG_PATH}"
fi

# ============================================================================
# 5. 测试连通性
# ============================================================================
echo ""
info "测试腾讯云 ASR 连通性..."

TEST_RESULT=$(uv run python -c "
import sys, os
sys.path.insert(0, '${PROJECT_ROOT}')
from server.config import get_tencent_creds
creds = get_tencent_creds()
print('OK: secret_id={}'.format(creds['secret_id'][:8] + '...'))
" 2>&1)

if echo "$TEST_RESULT" | grep -q "^OK:"; then
    info "$TEST_RESULT"
else
    error "腾讯云凭证测试失败: $TEST_RESULT"
    error "请检查 SecretId / SecretKey 是否正确"
    exit 1
fi

# ============================================================================
# 6. 安装 Skill 到 Claude Code
# ============================================================================
echo ""
SKILL_DIR="${HOME}/.claude/skills/transcribe"
info "安装 Skill 到 Claude Code..."
echo ""

if [ -d "$SKILL_DIR" ]; then
    confirm "发现已有 Skill，是否覆盖？(y/N)"
    if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
        rm -rf "$SKILL_DIR"
    else
        info "跳过 Skill 安装（现有 ${SKILL_DIR} 保持不变）"
        SKILL_INSTALLED=skip
    fi
fi

if [ "${SKILL_INSTALLED:-}" != "skip" ]; then
    mkdir -p "$(dirname "$SKILL_DIR")"

    # 复制 skill 文件，动态替换 manifest 中的路径占位符
    mkdir -p "$SKILL_DIR"
    cp "${PROJECT_ROOT}/transcribe/prompt.md" "$SKILL_DIR/prompt.md"

    # 替换 manifest 中的项目路径为实际安装路径
    sed "s|__PROJECT_PATH__|${PROJECT_ROOT}|g" \
        "${PROJECT_ROOT}/transcribe/manifest.json" \
        > "$SKILL_DIR/manifest.json"

    info "Skill 已安装到 ${SKILL_DIR}"
    info "请重启 Claude Code 使 Skill 生效"
fi

# ============================================================================
# 7. 注册 MCP Server（Claude Code）
# ============================================================================
echo ""
info "注册 MCP Server..."

# 自动注册（静默模式，已知路径）
if uv run mcp install "${PROJECT_ROOT}/server/server.py" 2>/dev/null; then
    info "MCP Server 注册完成"
else
    info "MCP Server 注册失败，请手动运行："
    echo "    uv run mcp install ${PROJECT_ROOT}/server/server.py"
fi

# ============================================================================
# 完成
# ============================================================================
echo ""
echo "======================================"
echo -e "  ${GREEN}安装完成！${NC}"
echo "======================================"
echo ""
echo "下一步："
echo "  1. 在 Claude Code 中使用 /transcribe 命令"
echo "  2. 或直接调用 MCP tool: transcribe_video"
echo ""
echo "配置路径: ${CONFIG_PATH}"
echo ""
