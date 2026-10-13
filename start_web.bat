@echo off
chcp 950 >nul
title 法拍屋與實價登錄智慧比對系統 - 網頁版
cd /d "%~dp0"

set "PYBIN=C:\Users\tsai_\AppData\Local\Programs\Python\Python312\python.exe"

echo ===================================================
echo  正在啟動【法拍屋 x 實價登錄】網頁版伺服器...
echo  即將自動為您開啟瀏覽器 (http://localhost:5000)
echo ===================================================
echo.

start "" "http://localhost:5000"

if exist "%PYBIN%" (
    "%PYBIN%" app.py
) else (
    python app.py
)

pause
