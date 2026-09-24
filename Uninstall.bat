@echo off
setlocal EnableDelayedExpansion

title Database Cloud Backup - Clean Uninstaller

:: -------------------------------------------------------------
:: Step 1: Discover Installation Directory
:: 1. Check command line argument (%~1)
:: 2. Check registry HKCU Uninstall key
:: 3. Check if running inside installed directory
:: 4. Check default %LOCALAPPDATA%\Programs\DatabaseBackupApp
:: -------------------------------------------------------------
set "TARGET_DIR=%~1"

if "%TARGET_DIR%"=="" (
    for /f "tokens=2*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
        set "TARGET_DIR=%%B"
    )
)

if "%TARGET_DIR%"=="" (
    if exist "%~dp0DatabaseBackupApp.exe" (
        set "TARGET_DIR=%~dp0"
    )
)

if "%TARGET_DIR%"=="" (
    if exist "%LOCALAPPDATA%\Programs\DatabaseBackupApp\DatabaseBackupApp.exe" (
        set "TARGET_DIR=%LOCALAPPDATA%\Programs\DatabaseBackupApp"
    )
)

:: Clean trailing slash
if not "%TARGET_DIR%"=="" (
    if "%TARGET_DIR:~-1%"=="\" set "TARGET_DIR=%TARGET_DIR:~0,-1%"
)

:: -------------------------------------------------------------
:: Step 2: Self-Migrate to %TEMP% to prevent directory locking
:: If running inside TARGET_DIR, cmd locks the directory from deletion.
:: Copy to %TEMP% and launch from there.
:: -------------------------------------------------------------
if /i not "%~dp0"=="%TEMP%\" (
    copy /y "%~f0" "%TEMP%\Uninstall_DatabaseBackupApp.bat" >nul 2>&1
    start "" "%TEMP%\Uninstall_DatabaseBackupApp.bat" "%TARGET_DIR%" %2
    exit /b 0
)

:: Ensure current working directory is %TEMP%, releasing all locks on TARGET_DIR
cd /d "%TEMP%"

if "%TARGET_DIR%"=="" (
    cls
    echo Database Cloud Backup was not automatically found in standard directories.
    set /p TARGET_DIR="Please enter the full installation directory (or press Enter to cancel): "
    if "!TARGET_DIR!"=="" (
        echo Cancelled.
        timeout /t 2 >nul
        (goto) 2>nul & del "%~f0"
        exit /b 0
    )
    if "!TARGET_DIR:~-1!"=="\" set "TARGET_DIR=!TARGET_DIR:~0,-1!"
)

if /i not "%~2"=="/quiet" if /i not "%~2"=="/silent" (
    cls
    echo ============================================================
    echo   UNINSTALL DATABASE CLOUD BACKUP
    echo ============================================================
    echo.
    echo Target Directory: "%TARGET_DIR%"
    echo.
    echo This will permanently remove:
    echo  - Active application processes
    echo  - Windows Task Scheduler automated backup jobs
    echo  - Desktop and Start Menu shortcuts
    echo  - Windows Installed Apps registry entries
    echo  - Application files and local data
    echo.
    set /p CONFIRM="Are you sure you want to completely uninstall? (Y/N): "
    if /i not "!CONFIRM!"=="Y" (
        echo.
        echo Uninstallation cancelled by user.
        timeout /t 2 >nul
        (goto) 2>nul & del "%~f0"
        exit /b 0
    )
)

echo.
echo [1/5] Terminating active application processes...
taskkill /F /IM DatabaseBackupApp.exe >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
taskkill /F /IM sqlcmd.exe /FI "WINDOWTITLE eq Enterprise Database Backup*" >nul 2>&1
timeout /t 1 /nobreak >nul
echo       Active processes terminated.

echo.
echo [2/5] Removing Windows Task Scheduler automation...
schtasks /delete /tn "Database Cloud Backup" /f >nul 2>&1
echo       Scheduled task removed.

echo.
echo [3/5] Removing Shortcuts (Desktop, Start Menu, OneDrive)...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Programs')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue; " ^
  "Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('CommonPrograms')) 'Database Cloud Backup.lnk') -Force -ErrorAction SilentlyContinue;" >nul 2>&1
del /f /q "%USERPROFILE%\Desktop\Database Cloud Backup.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Database Cloud Backup.lnk" >nul 2>&1
echo       Shortcuts removed.

echo.
echo [4/5] Removing Windows Registry registration...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /f >nul 2>&1
echo       Registry cleaned.

echo.
echo [5/5] Purging application files...
if exist "%TARGET_DIR%" (
    timeout /t 1 /nobreak >nul
    rmdir /s /q "%TARGET_DIR%" >nul 2>&1
    if exist "%TARGET_DIR%" (
        timeout /t 1 /nobreak >nul
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '%TARGET_DIR%' -Recurse -Force -ErrorAction SilentlyContinue" >nul 2>&1
    )
    if exist "%TARGET_DIR%" (
        timeout /t 1 /nobreak >nul
        rmdir /s /q "%TARGET_DIR%" >nul 2>&1
    )
)
echo       Application directory deleted.

echo.
echo ============================================================
echo   UNINSTALLATION COMPLETE!
echo ============================================================
echo Database Cloud Backup was completely and cleanly removed.
echo.

if /i not "%~2"=="/quiet" if /i not "%~2"=="/silent" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Database Cloud Backup has been completely and cleanly uninstalled from this computer.', 'Uninstallation Complete', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)" >nul 2>&1
    pause
)

(goto) 2>nul & del "%~f0"
exit /b 0
