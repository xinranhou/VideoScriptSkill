# Claude Code Voice Input - Quick Start
# 运行此脚本启动语音输入服务

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Claude Code Voice Input Starter" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$voiceScript = Join-Path $scriptPath "voice_input.py"

if (-not (Test-Path $voiceScript)) {
    Write-Host "[ERROR] voice_input.py not found!" -ForegroundColor Red
    Write-Host "Make sure you're running this script from the project directory." -ForegroundColor Yellow
    exit 1
}

Write-Host "[*] Starting voice input service..." -ForegroundColor Green
Write-Host "[*] Hotkey: Right-Alt (AltGr)" -ForegroundColor Yellow
Write-Host "[*] Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

# 在当前会话运行（会占用终端）
# 如果想在后台运行，删除 -NoExit
python -u $voiceScript
