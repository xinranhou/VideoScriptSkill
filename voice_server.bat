@echo off
REM Claude Code Voice Input Launcher
REM 运行此脚本启动语音输入，然后启动 Claude Code

echo ========================================
echo    Claude Code Voice Input Launcher
echo ========================================
echo.
echo 正在启动语音输入服务...

REM 在后台启动语音输入脚本（新窗口）
start "VoiceInput" python -u "%~dp0voice_input.py"

REM 等待2秒让服务启动
timeout /t 2 /nobreak > nul

echo 语音输入服务已启动！
echo 热键: 右Alt
echo.
echo 按任意键启动 Claude Code...
pause > nul

REM 启动 Claude Code
claude
