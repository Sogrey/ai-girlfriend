@echo off
title AI 女友
cd /d "%~dp0\.."

echo ================================================
echo   AI 桌面女友  -  启动中...
echo ================================================
echo.

REM ---- 1. 检查依赖 ----
if not exist ".venv\Scripts\python.exe" (
  echo [X] Python 虚拟环境不存在 (.venv)
  echo     请先运行: pip install 或联系开发者
  echo.
  pause
  exit /b 1
)
if not exist "node_modules\electron\dist\electron.exe" (
  echo [X] Node 依赖未安装 (node_modules)
  echo     请先运行: npm install
  echo.
  pause
  exit /b 1
)
echo [OK] 依赖检查通过

REM ---- 2. 启动 Python 后端 ----
echo.
echo [1/3] 启动 Python 后端 (WebSocket 127.0.0.1:8765)...
start "AI-Girlfriend-Backend" /min .venv\Scripts\pythonw.exe backend\main.py

REM ---- 3. 等待后端就绪 ----
echo [2/3] 等待后端就绪...
set /a tries=0
:wait_backend
powershell -NoProfile -Command "try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); exit 0 }catch{ exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
  set /a tries+=1
  if !tries! geq 40 (
    echo [X] 后端启动超时 (40s)
    echo     请检查 Ollama / 网络 / Python 环境
    pause
    exit /b 1
  )
  timeout /t 1 /nobreak >nul 2>&1
  goto wait_backend
)
echo       后端已就绪

REM ---- 4. 启动 Electron ----
echo.
echo [3/3] 启动 3D 桌面女友...
echo.
echo 提示: Ctrl+Alt+G 召唤/隐藏  |  Ctrl+Shift+I 开发者工具
echo ================================================
npx electron .

REM ---- 5. Electron 退出后清理后端 ----
echo.
echo 清理后端进程...
taskkill /FI "WindowTitle eq AI-Girlfriend-Backend" /T /F >nul 2>&1
echo 已退出。
