@echo off
cd /d "%~dp0"
echo ============================================================
echo   MAA auto-close LDPlayer watcher
echo   (keep this window open; close it to stop watching)
echo ============================================================
echo.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0maa-autoclose.ps1"
echo.
echo Watcher stopped. Press any key to close.
pause >nul
