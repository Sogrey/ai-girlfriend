@echo off
title AI 女友 - 首次安装
cd /d "%~dp0\.."

echo ==================================================
echo   3D 桌面 AI 女友  -  首次环境安装
echo ==================================================
echo.

REM ---- 1. 检查 Node.js ----
where node >nul 2>&1
if %errorlevel% neq 0 (
  echo [X] 未检测到 Node.js
  echo     请先安装 Node.js 18+ : https://nodejs.org
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do set NODE_VER=%%v
echo [OK] Node.js %NODE_VER%

REM ---- 2. 检查 Python ----
where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [X] 未检测到 Python
  echo     请先安装 Python 3.10+ : https://python.org
  echo.
  pause
  exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do set PY_VER=%%v
echo [OK] %PY_VER%
echo.

REM ---- 3. 安装 Node 依赖 ----
echo [1/4] 安装 Node 依赖 (electron + three.js + three-vrm)...
call npm install --no-audit --no-fund
if %errorlevel% neq 0 (
  echo [X] npm install 失败
  echo     如网络问题，可手动设置镜像: npm config set registry https://registry.npmmirror.com
  pause
  exit /b 1
)
echo       Node 依赖安装完成
echo.

REM ---- 4. 创建 Python 虚拟环境 ----
echo [2/4] 创建 Python 虚拟环境 (.venv)...
if exist ".venv\Scripts\python.exe" (
  echo       .venv 已存在，跳过创建
) else (
  python -m venv .venv
  if %errorlevel% neq 0 (
    echo [X] 创建虚拟环境失败
    pause
    exit /b 1
  )
)
echo       虚拟环境就绪
echo.

REM ---- 5. 安装 Python 依赖 ----
echo [3/4] 安装 Python 依赖 (faster-whisper + edge-tts + websockets)...
.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
if %errorlevel% neq 0 (
  echo [!] pip 升级失败，继续安装依赖...
)
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
  echo [X] Python 依赖安装失败
  echo     如网络问题，可手动切换镜像后重试
  pause
  exit /b 1
)
echo       Python 依赖安装完成
echo.

REM ---- 6. 检查 VRM 模型 ----
echo [4/4] 检查 VRM 模型文件...
if exist "assets\models\default.vrm" (
  echo       默认模型存在
) else (
  echo [!] 未找到默认 VRM 模型 (assets\models\default.vrm)
  echo     程序仍可启动，但角色将无法显示
  echo     请从 VRoid Hub 下载 VRM 文件放入该路径
  echo.
)

REM ---- 7. 完成 ----
echo ==================================================
echo   安装完成!
echo.
echo   下一步:
echo   1. 双击 scripts\启动AI女友.bat 启动程序
echo   2. 角色出现后点底部 ?? 填写 DeepSeek API Key
echo   3. 开始对话!
echo.
echo   API Key 获取: https://platform.deepseek.com
echo ==================================================
echo.
pause
