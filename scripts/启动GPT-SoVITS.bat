@echo off
chcp 65001 >nul
title GPT-SoVITS Local TTS (port 9880)

REM ---- GPT-SoVITS local TTS service (api_v2, zero-key offline voice) ----
REM First run needs the models in D:\AI\GPT-SoVITS\GPT_SoVITS\pretrained_models
REM (gsv-v2final-pretrained + chinese-hubert-base + chinese-roberta-wwm-ext-large).

if not exist "D:\AI\GPT-SoVITS\api_v2.py" (
  echo [X] GPT-SoVITS not found: D:\AI\GPT-SoVITS
  echo     Run the setup first, or check the install path.
  pause
  exit /b 1
)
if not exist "D:\AI\GPT-SoVITS\venv\Scripts\python.exe" (
  echo [X] Runtime venv not found: D:\AI\GPT-SoVITS\venv
  echo     Environment setup incomplete - see D:\AI\GPT-SoVITS\setup_env.ps1
  pause
  exit /b 1
)
if not exist "D:\AI\GPT-SoVITS\GPT_SoVITS\pretrained_models\gsv-v2final-pretrained\s2G2333k.pth" (
  echo [X] Pretrained models not downloaded yet:
  echo     D:\AI\GPT-SoVITS\GPT_SoVITS\pretrained_models\gsv-v2final-pretrained
  echo     Run: python D:\AI\GPT-SoVITS\download_models.py
  pause
  exit /b 1
)

cd /d D:\AI\GPT-SoVITS
echo ================================================
echo   GPT-SoVITS api_v2 - starting on 127.0.0.1:9880
echo   (GPU ~3-4GB; keep this window open while using
echo    the local voice. First synthesis warms up.)
echo ================================================
"venv\Scripts\python.exe" api_v2.py -a 127.0.0.1 -p 9880
echo.
echo Service stopped.
pause
