@echo off
setlocal EnableDelayedExpansion
title Database Cloud Backup - Clean Uninstaller

:: 1. Identify Target Installation Directory
set "TARGET_DIR=%~dp0"
if "!TARGET_DIR:~-1!"=="\" set "TARGET_DIR=!TARGET_DIR:~0,-1!"

:: 2. Interactive Confirmation (only if not silent)
if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    cls
    echo ============================================================
    echo   DATABASE CLOUD BACKUP - UNINSTALLER
    echo ============================================================
    echo.
    echo Target Installation Directory:
    echo   !TARGET_DIR!
    echo.
    echo This will cleanly remove:
    echo   - Running application processes
    echo   - Windows Task Scheduler automated backup jobs
    echo   - Desktop and Start Menu shortcuts
    echo   - Windows Installed Apps registry entries
    echo   - Application binaries and configurations
    echo.
    set /p CONFIRM="Are you sure you want to completely uninstall? (Y/N): "
    if /i not "!CONFIRM!"=="Y" (
        echo.
        echo Uninstallation cancelled by user.
        ping 127.0.0.1 -n 3 >nul
        exit /b 0
    )
)

echo.
echo [1/5] Terminating active application processes...
taskkill /F /IM DatabaseBackupApp.exe >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
taskkill /F /IM sqlcmd.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
ping 127.0.0.1 -n 2 >nul

echo [2/5] Removing Windows Task Scheduler tasks...
schtasks /delete /tn "Database Cloud Backup" /f >nul 2>&1
schtasks /delete /tn "Database Cloud Backup (System Service)" /f >nul 2>&1
schtasks /delete /tn "EnterpriseDatabaseBackup" /f >nul 2>&1

echo [3/5] Removing Desktop and Start Menu shortcuts...
del /f /q "%USERPROFILE%\Desktop\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%PUBLIC%\Desktop\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs\*Database*Backup*.lnk" >nul 2>&1

echo [4/5] Removing Windows Registry registration...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1

echo [5/5] Purging application directory...
cd /d "%TEMP%"
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 1; Remove-Item -LiteralPath '!TARGET_DIR!' -Recurse -Force -ErrorAction SilentlyContinue"

echo.
echo ============================================================
echo   UNINSTALLATION COMPLETE!
echo ============================================================
echo Database Cloud Backup was completely and cleanly removed.
echo.

if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Database Cloud Backup has been completely and cleanly uninstalled from this computer.', 'Uninstallation Complete', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)" >nul 2>&1
)

exit /b 0
