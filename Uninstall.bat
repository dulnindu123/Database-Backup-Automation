@echo off
setlocal EnableDelayedExpansion
title Database Cloud Backup - Clean Uninstaller

REM 1. Identify Target Installation Directory
set "TARGET_DIR="

REM Check registry for InstallLocation
for /f "tokens=2*" %%A in ('reg.exe query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
    set "TARGET_DIR=%%B"
)
if "!TARGET_DIR!"=="" (
    for /f "tokens=2*" %%A in ('reg.exe query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
        set "TARGET_DIR=%%B"
    )
)

REM If not found in registry, check standard Program Files
if "!TARGET_DIR!"=="" (
    if exist "%ProgramFiles%\DatabaseBackupApp\DatabaseBackupApp.exe" (
        set "TARGET_DIR=%ProgramFiles%\DatabaseBackupApp"
    )
)

REM If running directly inside the installed application directory (not installer package)
if "!TARGET_DIR!"=="" (
    set "CURR_DIR=%~dp0"
    if "!CURR_DIR:~-1!"=="\" set "CURR_DIR=!CURR_DIR:~0,-1!"
    if exist "!CURR_DIR!\DatabaseBackupApp.exe" if not exist "!CURR_DIR!\Setup_DatabaseBackup.exe" (
        set "TARGET_DIR=!CURR_DIR!"
    )
)

REM Safety check: Never delete the installer package directory itself!
set "SCRIPT_DIR=%~dp0"
if "!SCRIPT_DIR:~-1!"=="\" set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
if exist "!SCRIPT_DIR!\Setup_DatabaseBackup.exe" (
    if /i "!TARGET_DIR!"=="!SCRIPT_DIR!" (
        set "TARGET_DIR=%ProgramFiles%\DatabaseBackupApp"
    )
)

if not "!TARGET_DIR!"=="" (
    if "!TARGET_DIR:~-1!"=="\" set "TARGET_DIR=!TARGET_DIR:~0,-1!"
)

set "DATA_DIR=%ALLUSERSPROFILE%\DatabaseBackupApp"

REM 2. Interactive Confirmation (only if not silent)
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
    
    REM Prompt to archive the single unified backup_log.txt
    set "ARCHIVE_LOG=Y"
    set /p ARCHIVE_LOG="Preserve single audit log [backup_log.txt] to your Desktop? (Y/N, default Y): "
    if /i not "!ARCHIVE_LOG!"=="N" (
        if exist "!DATA_DIR!\backup_log.txt" (
            copy /y "!DATA_DIR!\backup_log.txt" "%USERPROFILE%\Desktop\backup_log_archive.txt" >nul 2>&1
            echo       [OK] Audit log exported to %USERPROFILE%\Desktop\backup_log_archive.txt
        ) else if exist "!TARGET_DIR!\backup_log.txt" (
            copy /y "!TARGET_DIR!\backup_log.txt" "%USERPROFILE%\Desktop\backup_log_archive.txt" >nul 2>&1
            echo       [OK] Audit log exported to %USERPROFILE%\Desktop\backup_log_archive.txt
        )
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
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 1; Remove-Item -LiteralPath '!TARGET_DIR!' -Recurse -Force -ErrorAction SilentlyContinue; if (Test-Path '!DATA_DIR!') { Remove-Item -LiteralPath '!DATA_DIR!' -Recurse -Force -ErrorAction SilentlyContinue }"

echo.
echo ============================================================
echo   UNINSTALLATION COMPLETE
echo ============================================================
echo Database Cloud Backup was completely and cleanly removed.
echo.

if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Database Cloud Backup has been completely and cleanly uninstalled from this computer.', 'Uninstallation Complete', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)" >nul 2>&1
)

exit /b 0
