@echo off
title AI Girlfriend - First-time Setup
cd /d "%~dp0\.."

echo ==================================================
echo   3D Desktop AI Girlfriend - First-time Setup
echo ==================================================
echo.

REM ---- 1. Check Node.js ----
where node >nul 2>&1
if %errorlevel% neq 0 (
  echo [X] Node.js not found
  echo     Install Node.js 18+ from https://nodejs.org
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do set NODE_VER=%%v
echo [OK] Node.js %NODE_VER%

REM ---- 2. Check Python ----
where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [X] Python not found
  echo     Install Python 3.10+ from https://python.org
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do set PY_VER=%%v
echo [OK] %PY_VER%
echo.

REM ---- 3. Install Node dependencies ----
echo [1/4] Installing Node dependencies: electron + three.js + three-vrm ...
call npm install --no-audit --no-fund
if %errorlevel% neq 0 (
  echo [X] npm install failed
  echo     For network issues set mirror: npm config set registry https://registry.npmmirror.com
  pause
  exit /b 1
)
echo       Node dependencies installed
echo.

REM ---- 4. Create Python venv ----
echo [2/4] Creating Python virtual environment .venv ...
if exist ".venv\Scripts\python.exe" (
  echo       .venv already exists, skip
) else (
  python -m venv .venv
  if %errorlevel% neq 0 (
    echo [X] Failed to create virtual environment
    pause
    exit /b 1
  )
)
echo       Virtual environment ready
echo.

REM ---- 5. Install Python dependencies ----
echo [3/4] Installing Python dependencies: faster-whisper + edge-tts + websockets ...
.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
if %errorlevel% neq 0 (
  echo [!] pip upgrade failed, continue with dependencies...
)
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
  echo [X] Python dependencies install failed
  echo     Switch mirror and retry if network issue
  pause
  exit /b 1
)
echo       Python dependencies installed
echo.

REM ---- 6. Check VRM model ----
echo [4/4] Checking VRM model file ...
if exist "assets\models\default.vrm" (
  echo       Default model found
) else (
  echo [!] Default VRM model not found: assets\models\default.vrm
  echo     App still starts, but the character will not show
  echo     Download a VRM file from VRoid Hub into that path
  echo.
)

REM ---- 7. Done ----
echo ==================================================
echo   Setup complete!
echo.
echo   Next steps:
echo   1. Double-click scripts\??AI??.bat to start
echo   2. Fill DeepSeek API Key via the toolbar settings button
echo   3. Start chatting!
echo.
echo   API Key: https://platform.deepseek.com
echo ==================================================
echo.
pause
