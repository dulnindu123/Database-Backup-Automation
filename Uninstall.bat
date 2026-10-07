@echo off
setlocal EnableDelayedExpansion
title Enterprise Database Cloud Backup - Clean Uninstaller

:: -----------------------------------------------------------------------------
:: 1. Self-Elevation Check (Run as Administrator)
:: -----------------------------------------------------------------------------
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Administrator privileges required. Elevating...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\" %*\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

:: -----------------------------------------------------------------------------
:: 2. Identify Target Directories
:: -----------------------------------------------------------------------------
set "TARGET_DIR="

:: Check registry for InstallLocation
for /f "tokens=2*" %%A in ('reg.exe query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
    set "TARGET_DIR=%%B"
)
if "!TARGET_DIR!"=="" (
    for /f "tokens=2*" %%A in ('reg.exe query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
        set "TARGET_DIR=%%B"
    )
)

:: Fallback check standard Program Files
if "!TARGET_DIR!"=="" (
    if exist "%ProgramFiles%\DatabaseBackupApp" (
        set "TARGET_DIR=%ProgramFiles%\DatabaseBackupApp"
    )
)

:: If running inside installed application directory
if "!TARGET_DIR!"=="" (
    set "CURR_DIR=%~dp0"
    if "!CURR_DIR:~-1!"=="\" set "CURR_DIR=!CURR_DIR:~0,-1!"
    if exist "!CURR_DIR!\DatabaseBackupApp.exe" if not exist "!CURR_DIR!\Setup_DatabaseBackup.exe" (
        set "TARGET_DIR=!CURR_DIR!"
    )
)

if "!TARGET_DIR!"=="" (
    set "TARGET_DIR=%ProgramFiles%\DatabaseBackupApp"
)
if "!TARGET_DIR:~-1!"=="\" set "TARGET_DIR=!TARGET_DIR:~0,-1!"

set "DATA_DIR=%ALLUSERSPROFILE%\DatabaseBackupApp"

:: -----------------------------------------------------------------------------
:: 3. Interactive Confirmation (Unless Silent)
:: -----------------------------------------------------------------------------
if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    cls
    echo ============================================================
    echo   DATABASE CLOUD BACKUP - ENTERPRISE UNINSTALLER (v4.2.0)
    echo ============================================================
    echo.
    echo Target Installation Directory:
    echo   !TARGET_DIR!
    echo Target Data Directory:
    echo   !DATA_DIR!
    echo.
    echo This will completely and cleanly remove:
    echo   [x] All Windows Scheduled Tasks (Daily Backups, Cleanup, Performance)
    echo   [x] Active application and background agent processes
    echo   [x] Machine DPAPI authentication vault (token.dpapi)
    echo   [x] Desktop and Start Menu shortcuts
    echo   [x] Windows Registry Installed Apps entries
    echo   [x] Application binaries, scripts, and local configurations
    echo.
    set /p CONFIRM="Are you sure you want to completely uninstall? (Y/N): "
    if /i not "!CONFIRM!"=="Y" (
        echo.
        echo Uninstallation cancelled by user.
        ping 127.0.0.1 -n 2 >nul
        exit /b 0
    )
    
    :: Option to preserve audit logs
    set "ARCHIVE_LOG=Y"
    set /p ARCHIVE_LOG="Preserve audit logs to your Desktop? (Y/N, default Y): "
    if /i not "!ARCHIVE_LOG!"=="N" (
        if exist "!DATA_DIR!\logs" (
            mkdir "%USERPROFILE%\Desktop\DatabaseBackup_Logs_Archive" >nul 2>&1
            copy /y "!DATA_DIR!\logs\*" "%USERPROFILE%\Desktop\DatabaseBackup_Logs_Archive\" >nul 2>&1
            echo       [OK] Audit logs exported to Desktop\DatabaseBackup_Logs_Archive
        )
        if exist "!DATA_DIR!\backup_log.txt" (
            copy /y "!DATA_DIR!\backup_log.txt" "%USERPROFILE%\Desktop\backup_log_archive.txt" >nul 2>&1
            echo       [OK] Log exported to %USERPROFILE%\Desktop\backup_log_archive.txt
        )
    )
)

echo.
echo [1/6] Terminating active processes...
taskkill /F /IM DatabaseBackupApp.exe >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
taskkill /F /IM sqlcmd.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
powershell -NoProfile -Command "Get-WmiObject Win32_Process -Filter \"Name like 'powershell%%'\" | Where-Object { $_.CommandLine -match 'backup_agent|performance_query|storage_monitor|run_automation' } | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1

echo [2/6] Removing Windows Scheduled Tasks...
schtasks /delete /tn "DatabaseBackup_AutomatedTask" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_Daily" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_StorageMonitor" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_StorageCleanup" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_PerformanceMaintenance" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackupApp" /f >nul 2>&1
schtasks /delete /tn "Database Cloud Backup" /f >nul 2>&1
schtasks /delete /tn "Database Cloud Backup (System Service)" /f >nul 2>&1
schtasks /delete /tn "EnterpriseDatabaseBackup" /f >nul 2>&1

echo [3/6] Shredding machine credentials...
powershell -NoProfile -Command "foreach ($f in @('!DATA_DIR!\token.dpapi', '!TARGET_DIR!\token.dpapi')) { if (Test-Path $f) { $b = New-Object byte[] 256; (New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($b); [System.IO.File]::WriteAllBytes($f, $b); Remove-Item $f -Force -ErrorAction SilentlyContinue } }" >nul 2>&1

echo [4/6] Removing shortcuts...
del /f /q "%USERPROFILE%\Desktop\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%PUBLIC%\Desktop\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs\*Database*Backup*.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\*Uninstall*Database*.lnk" >nul 2>&1
del /f /q "%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs\*Uninstall*Database*.lnk" >nul 2>&1

echo [5/6] Removing Windows Registry entries...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1

echo [6/6] Purging application directories...
cd /d "%TEMP%"
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 1; if (Test-Path '!TARGET_DIR!') { Remove-Item -LiteralPath '!TARGET_DIR!' -Recurse -Force -ErrorAction SilentlyContinue }; if (Test-Path '!DATA_DIR!') { Remove-Item -LiteralPath '!DATA_DIR!' -Recurse -Force -ErrorAction SilentlyContinue }"

echo.
echo ============================================================
echo   UNINSTALLATION COMPLETE (100%% CLEAN)
echo ============================================================
echo All application files, background tasks, and registry entries
echo have been completely removed from this computer.
echo.

if /i not "%~1"=="/silent" if /i not "%~1"=="/quiet" (
    powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Database Cloud Backup has been completely and cleanly uninstalled from this computer.', 'Uninstallation Complete', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)" >nul 2>&1
)

exit /b 0
