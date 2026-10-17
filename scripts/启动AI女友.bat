@echo off
chcp 65001 >nul
title AI Girlfriend (Tauri)
cd /d "%~dp0\.."

echo ================================================
echo   AI Girlfriend (Tauri 2) - Starting...
echo ================================================
echo.

REM ---- 1. Check dependencies ----
if not exist ".venv\Scripts\python.exe" (
  echo [X] Python venv not found: .venv
  echo     Run the first-time setup script, or see README.md
  echo.
  pause
  exit /b 1
)
where cargo >nul 2>&1
if errorlevel 1 (
  echo [X] Rust toolchain (cargo) not found in PATH.
  echo     Install from https://rustup.rs then reopen this terminal.
  echo.
  pause
  exit /b 1
)
echo [OK] Dependencies ready

REM ---- 2. Run the Tauri shell ----
echo.
echo   The Rust shell auto-starts the Python backend on 8765
echo   (or reuses one that is already running).
echo   Summon hotkey: Ctrl+Alt+G ^(or the tray menu^)
echo ================================================
echo.
cargo run --manifest-path src-tauri/Cargo.toml

echo.
echo Exited.
pause
