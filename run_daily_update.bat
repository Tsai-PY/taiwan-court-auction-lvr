@echo off
chcp 950 >nul
title 司法院法拍屋與實價登錄比對
cd /d "%~dp0"

set "PYBIN=C:\Users\tsai_\AppData\Local\Programs\Python\Python312\python.exe"

if exist "%PYBIN%" (
    "%PYBIN%" daily_court_lvr_runner.py
) else (
    python daily_court_lvr_runner.py
)

echo.
echo ===================================================
echo [完成] 比對作業已完成！已產出最新報表。
echo ===================================================
echo.
pause
