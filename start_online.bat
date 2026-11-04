@echo off
setlocal
cd /d "%~dp0"
title Voice Studio - Online Cloudflare Tunnel

echo ============================================================
echo           Voice Studio - Localhost to Online Tunnel
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    pause
    exit /b 1
)

if not exist "cloudflared.exe" (
    echo [ERROR] cloudflared.exe not found in this folder.
    pause
    exit /b 1
)

echo Starting local server in the background...
start /b "" .venv\Scripts\python.exe -u server.py

timeout /t 4 /nobreak >nul

echo.
echo ============================================================
echo Starting Cloudflare Tunnel...
echo Copy the HTTPS link below to open Voice Studio on any device!
echo ============================================================
echo.

cloudflared.exe tunnel --url http://127.0.0.1:7860
pause
