@echo off
title AI Girlfriend
cd /d "%~dp0\.."

echo ================================================
echo   AI Girlfriend - Starting...
echo ================================================
echo.

REM ---- 1. Check dependencies ----
if not exist ".venv\Scripts\python.exe" (
  echo [X] Python venv not found: .venv
  echo     Run scripts\????.bat first, or see README.md
  echo.
  pause
  exit /b 1
)
if not exist "node_modules\electron\dist\electron.exe" (
  echo [X] Node modules not installed: node_modules
  echo     Run: npm install
  echo.
  pause
  exit /b 1
)
echo [OK] Dependencies ready

REM ---- 2. Start Python backend ----
echo.
echo [1/3] Starting Python backend - WebSocket 127.0.0.1:8765 ...
start "AI-Girlfriend-Backend" /min .venv\Scripts\pythonw.exe backend\main.py

REM ---- 3. Wait for backend ready ----
echo [2/3] Waiting for backend...
set /a tries=0
setlocal enabledelayedexpansion
:wait_backend
powershell -NoProfile -Command "try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',8765); $c.Close(); exit 0 }catch{ exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
  set /a tries+=1
  if !tries! geq 40 (
    echo [X] Backend start timeout: 40s
    echo     Check network / Python environment
    pause
    exit /b 1
  )
  timeout /t 1 /nobreak >nul 2>&1
  goto wait_backend
)
echo       Backend ready

REM ---- 4. Start Electron ----
echo.
echo [3/3] Starting desktop girlfriend...
echo.
echo Tips: Ctrl+Alt+G toggle show/hide  -  Ctrl+Shift+I DevTools
echo ================================================
npx electron .

REM ---- 5. Cleanup backend after Electron exits ----
echo.
echo Cleaning backend process...
taskkill /FI "WindowTitle eq AI-Girlfriend-Backend" /T /F >nul 2>&1
echo Exited.
