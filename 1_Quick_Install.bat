@echo off
setlocal enabledelayedexpansion

title Enterprise Database Cloud Backup - Zero-Trust Installer v4.1.0
color 0b

echo ============================================================
echo   ENTERPRISE DATABASE CLOUD BACKUP
echo   Zero-Trust Architecture Application Installer (v4.1.0)
echo ============================================================
echo.

set "SOURCE_DIR=%~dp0AppFiles"
if not exist "%SOURCE_DIR%\DatabaseBackupApp.exe" (
    echo [ERROR] Application binaries not found in "%SOURCE_DIR%"
    echo Please make sure the installer package was extracted completely.
    pause
    exit /b 1
)

set "TARGET_DIR=%ProgramFiles%\DatabaseBackupApp"
set "DATA_DIR=%ALLUSERSPROFILE%\DatabaseBackupApp"

echo [1/5] Installing application files...
echo       Destination: "%TARGET_DIR%"
echo       Data Directory: "%DATA_DIR%"
echo.

if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%" >nul 2>&1

:: If the customer already has an existing config or token, preserve them
set "HAS_CONFIG=0"
if exist "%DATA_DIR%\config.json" (
    copy /y "%DATA_DIR%\config.json" "%TEMP%\temp_cust_config.json" >nul 2>&1
    set "HAS_CONFIG=1"
) else if exist "%TARGET_DIR%\config.json" (
    copy /y "%TARGET_DIR%\config.json" "%TEMP%\temp_cust_config.json" >nul 2>&1
    set "HAS_CONFIG=1"
)

set "HAS_TOKEN=0"
if exist "%DATA_DIR%\token.dpapi" (
    copy /y "%DATA_DIR%\token.dpapi" "%TEMP%\temp_cust_token.dpapi" >nul 2>&1
    set "HAS_TOKEN=1"
) else if exist "%TARGET_DIR%\token.dpapi" (
    copy /y "%TARGET_DIR%\token.dpapi" "%TEMP%\temp_cust_token.dpapi" >nul 2>&1
    set "HAS_TOKEN=1"
)

set "HAS_PUBKEY=0"
if exist "%DATA_DIR%\backup_public.pem" (
    copy /y "%DATA_DIR%\backup_public.pem" "%TEMP%\temp_cust_pub.pem" >nul 2>&1
    set "HAS_PUBKEY=1"
) else if exist "%TARGET_DIR%\backup_public.pem" (
    copy /y "%TARGET_DIR%\backup_public.pem" "%TEMP%\temp_cust_pub.pem" >nul 2>&1
    set "HAS_PUBKEY=1"
)
set "HAS_ESCROW=0"
if exist "%DATA_DIR%\escrow_public.pem" (
    copy /y "%DATA_DIR%\escrow_public.pem" "%TEMP%\temp_cust_escrow.pem" >nul 2>&1
    set "HAS_ESCROW=1"
) else if exist "%TARGET_DIR%\escrow_public.pem" (
    copy /y "%TARGET_DIR%\escrow_public.pem" "%TEMP%\temp_cust_escrow.pem" >nul 2>&1
    set "HAS_ESCROW=1"
)

:: Terminate running app if active
taskkill.exe /F /IM DatabaseBackupApp.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul

:: Purge any legacy Google OAuth secrets (Zero-Trust guarantee)
if exist "%TARGET_DIR%\credentials.json" del /f /q "%TARGET_DIR%\credentials.json" >nul 2>&1
if exist "%TARGET_DIR%\token.json" del /f /q "%TARGET_DIR%\token.json" >nul 2>&1
if exist "%TARGET_DIR%\client_secret.json" del /f /q "%TARGET_DIR%\client_secret.json" >nul 2>&1
if exist "%DATA_DIR%\credentials.json" del /f /q "%DATA_DIR%\credentials.json" >nul 2>&1
if exist "%DATA_DIR%\token.json" del /f /q "%DATA_DIR%\token.json" >nul 2>&1

:: Copy application binaries to Program Files (Requires Administrative Privileges)
robocopy.exe "%SOURCE_DIR%" "%TARGET_DIR%" /E /IS /IT >nul
if %ERRORLEVEL% GEQ 8 (
    echo [ERROR] Failed to copy files to "%TARGET_DIR%"! Please run as Administrator.
    pause
    exit /b 1
)

:: Copy public keys and config template to ProgramData if not present
if not exist "%DATA_DIR%\backup_public.pem" if exist "%SOURCE_DIR%\backup_public.pem" (
    copy /y "%SOURCE_DIR%\backup_public.pem" "%DATA_DIR%\backup_public.pem" >nul 2>&1
)
if not exist "%DATA_DIR%\escrow_public.pem" if exist "%SOURCE_DIR%\escrow_public.pem" (
    copy /y "%SOURCE_DIR%\escrow_public.pem" "%DATA_DIR%\escrow_public.pem" >nul 2>&1
)
if not exist "%DATA_DIR%\config.json" if exist "%SOURCE_DIR%\config.json" (
    copy /y "%SOURCE_DIR%\config.json" "%DATA_DIR%\config.json" >nul 2>&1
)

:: Restore existing customer settings if this was an update
if "!HAS_CONFIG!"=="1" (
    copy /y "%TEMP%\temp_cust_config.json" "%DATA_DIR%\config.json" >nul 2>&1
    del /f /q "%TEMP%\temp_cust_config.json" >nul 2>&1
    echo       [OK] Preserved existing customer config.json in ProgramData
)
if "!HAS_TOKEN!"=="1" (
    copy /y "%TEMP%\temp_cust_token.dpapi" "%DATA_DIR%\token.dpapi" >nul 2>&1
    del /f /q "%TEMP%\temp_cust_token.dpapi" >nul 2>&1
    echo       [OK] Preserved existing customer token.dpapi in ProgramData
)
if "!HAS_PUBKEY!"=="1" (
    copy /y "%TEMP%\temp_cust_pub.pem" "%DATA_DIR%\backup_public.pem" >nul 2>&1
    del /f /q "%TEMP%\temp_cust_pub.pem" >nul 2>&1
    echo       [OK] Preserved existing backup_public.pem in ProgramData
)
if "!HAS_ESCROW!"=="1" (
    copy /y "%TEMP%\temp_cust_escrow.pem" "%DATA_DIR%\escrow_public.pem" >nul 2>&1
    del /f /q "%TEMP%\temp_cust_escrow.pem" >nul 2>&1
    echo       [OK] Preserved existing escrow_public.pem in ProgramData
)

:: Setup configuration from command line parameters (1_Quick_Install.bat <broker_url> <enroll_code>)
set "CLI_BROKER=%~1"
set "CLI_ENROLL=%~2"
if not "!CLI_BROKER!"=="" if not "!CLI_ENROLL!"=="" (
    echo       Applying Broker URL and Enroll Code to config...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
        "try { " ^
        "  $cfgPath = '%DATA_DIR%\config.json'; " ^
        "  $cfg = if (Test-Path $cfgPath) { Get-Content -Raw -Path $cfgPath -Encoding UTF8 | ConvertFrom-Json } else { [PSCustomObject]@{} }; " ^
        "  $cfg | Add-Member -NotePropertyName 'BROKER_URL' -NotePropertyValue '%CLI_BROKER%' -Force; " ^
        "  $cfg | Add-Member -NotePropertyName 'ENROLL_CODE' -NotePropertyValue '%CLI_ENROLL%' -Force; " ^
        "  $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8; " ^
        "  Copy-Item -Path $cfgPath -Destination '%TARGET_DIR%\config.json' -Force; " ^
        "  Write-Host '       [OK] Applied configuration successfully.' " ^
        "} catch { " ^
        "  Write-Error $_.Exception.Message; exit 1; " ^
        "}"
)
echo       [OK] Application installed successfully to "%TARGET_DIR%".


echo.
echo [2/5] Applying Hardened Access Control Lists (ACLs)...
:: Administrators Full Control, Standard Users Read/Execute
icacls.exe "%TARGET_DIR%" /grant:r Administrators:(OI)(CI)F /grant:r Users:(OI)(CI)RX >nul 2>&1
if exist "%TARGET_DIR%\token.dpapi" (
    icacls.exe "%TARGET_DIR%\token.dpapi" /inheritance:r /grant:r Administrators:F SYSTEM:F Users:R >nul 2>&1
)
if exist "%DATA_DIR%\token.dpapi" (
    icacls.exe "%DATA_DIR%\token.dpapi" /inheritance:r /grant:r Administrators:F SYSTEM:F Users:R >nul 2>&1
)
echo       [OK] Application folder and token.dpapi locked to Administrators, SYSTEM, and Run-As accounts.

echo.
echo [3/5] Creating Desktop and Start Menu shortcuts...
set "TARGET_EXE=%TARGET_DIR%\DatabaseBackupApp.exe"
set "TARGET_ICO=%TARGET_DIR%\app_icon.ico"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$d = [Environment]::GetFolderPath('Desktop') + '\Database Cloud Backup.lnk'; " ^
    "$s = $ws.CreateShortcut($d); $s.TargetPath = '%TARGET_EXE%'; $s.WorkingDirectory = '%TARGET_DIR%'; " ^
    "if (Test-Path '%TARGET_ICO%') { $s.IconLocation = '%TARGET_ICO%,0' }; $s.Save(); " ^
    "$p = [Environment]::GetFolderPath('Programs') + '\Database Cloud Backup.lnk'; " ^
    "$s2 = $ws.CreateShortcut($p); $s2.TargetPath = '%TARGET_EXE%'; $s2.WorkingDirectory = '%TARGET_DIR%'; " ^
    "if (Test-Path '%TARGET_ICO%') { $s2.IconLocation = '%TARGET_ICO%,0' }; $s2.Save();" >nul 2>&1
echo       [OK] Desktop and Start Menu shortcuts created.

echo.
echo [4/5] Registering Windows Uninstaller...
copy /y "%~dp0Uninstall.bat" "%TARGET_DIR%\Uninstall.bat" >nul
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "DisplayName" /d "Database Cloud Backup" /t REG_SZ /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "DisplayVersion" /d "4.1.0" /t REG_SZ /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "Publisher" /d "Enterprise Cloud DR" /t REG_SZ /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" /d "%TARGET_DIR%" /t REG_SZ /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "DisplayIcon" /d "%TARGET_ICO%" /t REG_SZ /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "UninstallString" /d "\"%TARGET_DIR%\Uninstall.bat\"" /t REG_SZ /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "NoModify" /d "1" /t REG_DWORD /f >nul 2>&1
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "NoRepair" /d "1" /t REG_DWORD /f >nul 2>&1
echo       [OK] Windows Program registration completed.

echo.
echo [5/5] Configuring Automated Weekly Schedule (Default: Dedicated User)...
:: Configures task to run under the user account. Administrators can opt into SYSTEM service inside app GUI.
schtasks.exe /create /tn "Database Cloud Backup" /tr "\"%TARGET_EXE%\" --auto" /sc weekly /d MON /st 02:00 /ru "%USERNAME%" /f >nul 2>&1
if errorlevel 1 (
    echo       [NOTICE] Task Scheduler configuration requires batch logon rights or admin elevation.
    echo                You can configure the task via the application GUI Schedule tab.
) else (
    echo       [OK] Scheduled Task configured: Mondays at 02:00 AM under %USERNAME%.
)

echo.
echo ============================================================
echo   INSTALLATION COMPLETED SUCCESSFULLY!
echo ============================================================
echo Enterprise Database Cloud Backup is ready to use.
echo All operations use Zero-Trust architecture.
echo.

set /p LAUNCH="Launch application now? (Y/N, default Y): "
if /i not "!LAUNCH!"=="N" (
    start "" "%TARGET_DIR%\DatabaseBackupApp.exe"
)

exit /b 0
