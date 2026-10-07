@echo off
title Admin Disaster Recovery Wizard
cd /d "%~dp0"

echo ============================================================
echo   ENTERPRISE DISASTER RECOVERY WIZARD (Admin Only)
echo ============================================================
echo Launching GUI Recovery Tool...

python decrypt_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Notice] Python GUI exited or failed. Launching CLI fallback...
    pause
)
