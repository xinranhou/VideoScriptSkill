# VideoScriptSkill 安装指南

## 本地 Claude Code 安装

### 1. 克隆项目

```bash
git clone https://github.com/你的用户名/VideoScriptSkill.git
cd VideoScriptSkill
```

### 2. 运行安装脚本

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

安装脚本会：
- 检查并安装依赖（uv、ffmpeg）
- 引导输入腾讯云和 MiniMax 凭证
- 测试 API 连通性
- 注册 MCP Server

### 3. 重启 Claude Code，开始使用

```bash
/transcribe /path/to/video.mp4
```

---

## 云端 Ubuntu OpenClaw 安装

### 1. SSH 连接服务器，安装系统依赖

```bash
sudo apt update && sudo apt install -y git curl
```

### 2. 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### 3. 克隆项目并运行安装

```bash
git clone https://github.com/你的用户名/VideoScriptSkill.git
cd VideoScriptSkill
chmod +x scripts/install.sh
./scripts/install.sh
```

### 4. 在 OpenClaw 中添加 MCP Server

在 OpenClaw 配置中添加：

```yaml
mcpServers:
  videoscripts:
    command: uv
    args:
      - run
      - python
      - /path/to/VideoScriptSkill/server/server.py
```

---

## 发布到 GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/你的用户名/VideoScriptSkill.git
git push -u origin main
```

---

## 凭证申请

### 腾讯云 ASR

1. 登录 https://console.cloud.tencent.com/
2. 搜索「ASR」→ 开通「一句话识别」
3. 访问管理 → API密钥管理 → 获取 SecretId/SecretKey

### MiniMax API Key

1. 登录 https://platform.minimax.chat/
2. API Keys → 创建新 Key
