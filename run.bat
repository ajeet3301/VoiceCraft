@echo off
setlocal
cd /d "%~dp0"

title VoiceCraft - Multilingual Voice Cloning Studio

echo ============================================================
echo           VoiceCraft - High-Fidelity Voice Cloning Studio
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv\Scripts\python.exe
    echo Please make sure .venv exists in this folder.
    echo.
    pause
    exit /b 1
)

:: Activate the project virtual environment
call .venv\Scripts\activate.bat

:: Set environment variables
set CHATTERBOX_MULTILINGUAL_T3_MODEL=v3
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

echo Virtual environment activated (.venv)
echo Model configuration: CHATTERBOX_MULTILINGUAL_T3_MODEL=v3
echo.
echo Launching VoiceCraft Web Studio...
echo Local URL: http://127.0.0.1:7860
echo.

:: Launch the default web browser after a brief delay
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:7860"

:: Run the VoiceCraft Web Studio server
python server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application stopped with error code %ERRORLEVEL%.
    pause
)
