@echo off
chcp 950 >nul
title 設定 Windows 每日自動排程

set "TASK_NAME=DailyCourtAuctionLvrSync"
set "BATCH_PATH=%~dp0run_daily_update.bat"

echo 正在註冊每日定時排程（每天 08:30 自動執行）...
schtasks /create /tn "%TASK_NAME%" /tr ""%BATCH_PATH%"" /sc daily /st 08:30 /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo [成功] 已成功建立每日定時排程！
    echo 工作名稱: %TASK_NAME%
    echo 執行時間: 每天 08:30 AM
) else (
    echo.
    echo [提示] 請在批次檔上點擊右鍵選擇「以系統管理員身分執行」。
)

echo.
pause
