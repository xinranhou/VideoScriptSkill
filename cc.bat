@echo off
setlocal enabledelayedexpansion

set CONFIG_FILE=%USERPROFILE%\.claude.json

if not exist "%CONFIG_FILE%" (
    echo {"env": {}} > "%CONFIG_FILE%"
)

echo ========================================
echo   Claude Code Provider Launcher
echo ========================================
echo.
echo   1. MiniMax
echo   2. Zhipu BigModel
echo   3. Kimi Moonshot
echo   4. Anthropic Official
echo   5. Exit
echo.
set /p choice="Select provider [1-5]: "

if "%choice%"=="1" goto minimax
if "%choice%"=="2" goto zhipu
if "%choice%"=="3" goto kimi
if "%choice%"=="4" goto anthropic
if "%choice%"=="5" goto end
goto end

:minimax
echo.
echo Launching MiniMax...
set ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
set ANTHROPIC_AUTH_TOKEN=sk-cp-Rdq7QQ9niGPzhvUBwBa7z5wYZAUfSoMARaCZh4xW8u63jdKJU5uvJC93YHyc592SJMWhSZNls63VNDAT0JoLIQ6yDZad8G9lmRgnW8E3zwSubBU8p31QGbM
set ANTHROPIC_MODEL=abab6.5s-chat
goto launch

:zhipu
echo.
echo Launching Zhipu BigModel...
set ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic
set ANTHROPIC_AUTH_TOKEN=123
set ANTHROPIC_MODEL=glm-4-plus
goto launch

:kimi
echo.
echo Launching Kimi Moonshot...
set ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic
set ANTHROPIC_AUTH_TOKEN=123
set ANTHROPIC_MODEL=moonshot-v1-8k
goto launch

:anthropic
echo.
echo Launching Anthropic Official...
set ANTHROPIC_BASE_URL=https://api.anthropic.com
set ANTHROPIC_AUTH_TOKEN=123
set ANTHROPIC_MODEL=claude-sonnet-4-20250514
goto launch

:launch
echo.
echo Provider: %ANTHROPIC_BASE_URL%
echo Model: %ANTHROPIC_MODEL%
echo.
echo Starting Claude Code...
claude
goto end

:end
endlocal
