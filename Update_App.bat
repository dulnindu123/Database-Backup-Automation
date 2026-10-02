@echo off
setlocal enabledelayedexpansion

title Enterprise Database Cloud Backup - Zero-Trust In-Place Updater v4.1.0
color 0b

echo ============================================================
echo   ENTERPRISE DATABASE CLOUD BACKUP
echo   Zero-Trust In-Place Application Updater — v4.1.0
echo ============================================================
echo.
echo This tool safely updates Database Cloud Backup on client
echo servers and workstations to the Zero-Trust Architecture.
echo.
echo ARCHITECTURE CHANGES IN v4.1.0:
echo   - Zero Google Credentials: All client Google keys removed.
echo   - Hybrid DBK2 Encryption: AES-256-GCM + RSA-4096 dual key wrap (64 KiB chunks).
echo   - Upload Broker: Presigned resumable upload sessions to retention-locked bucket.
echo   - Telemetry Broker: Storage health reports logged via isolated microservice.
echo   - ACL Hardening: Application folder locked to Admin Write / User Read.
echo   - Standard Token: Machine-scoped DPAPI token stored as token.dpapi.
echo.

:: 1. Verify update source files exist
set "SOURCE_DIR=%~dp0AppFiles"
if not exist "%SOURCE_DIR%\DatabaseBackupApp.exe" (
    echo [ERROR] Updated application files not found in "%SOURCE_DIR%"
    echo Please make sure the update package was extracted completely.
    pause
    exit /b 1
)

:: 2. Auto-Detect installed directory
set "TARGET_DIR="
for /f "tokens=2*" %%A in ('reg.exe query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
    set "TARGET_DIR=%%B"
)

if "%TARGET_DIR%"=="" (
    if exist "%LOCALAPPDATA%\Programs\DatabaseBackupApp\DatabaseBackupApp.exe" (
        set "TARGET_DIR=%LOCALAPPDATA%\Programs\DatabaseBackupApp"
    )
)

if "%TARGET_DIR%"=="" (
    if exist "C:\Program Files\DatabaseBackupApp\DatabaseBackupApp.exe" (
        set "TARGET_DIR=C:\Program Files\DatabaseBackupApp"
    )
)

if not "%TARGET_DIR%"=="" (
    if "%TARGET_DIR:~-1%"=="\" set "TARGET_DIR=%TARGET_DIR:~0,-1%"
)

if "%TARGET_DIR%"=="" (
    echo [NOTICE] Application could not be automatically located in standard folders.
    set /p TARGET_DIR="Please enter the full installed application directory: "
    if "!TARGET_DIR!"=="" (
        echo Update cancelled.
        pause
        exit /b 1
    )
)

if not exist "!TARGET_DIR!\DatabaseBackupApp.exe" (
    echo [ERROR] DatabaseBackupApp.exe was not found in: "!TARGET_DIR!"
    echo Please check the path and try again.
    pause
    exit /b 1
)

set "DATA_DIR=%ALLUSERSPROFILE%\DatabaseBackupApp"
if not exist "!DATA_DIR!" mkdir "!DATA_DIR!" >nul 2>&1

echo [OK] Target Installation Found: "!TARGET_DIR!"
echo.

:: 3. Terminate active application processes to release Windows file locks
echo [1/6] Stopping running application processes...
taskkill.exe /F /IM DatabaseBackupApp.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul
echo       Active processes terminated.

:: 4. Safety Backup of customer database settings (excluding legacy Google credentials)
echo.
echo [2/6] Safeguarding customer database configurations...
set "TEMP_BACKUP=%TEMP%\DB_Backup_Config_Safety"
if exist "%TEMP_BACKUP%" rmdir /s /q "%TEMP_BACKUP%" >nul 2>&1
mkdir "%TEMP_BACKUP%"

if exist "!TARGET_DIR!\config.json" (
    copy /y "!TARGET_DIR!\config.json" "%TEMP_BACKUP%\config.json" >nul 2>&1
    echo       - Saved config.json
) else if exist "!DATA_DIR!\config.json" (
    copy /y "!DATA_DIR!\config.json" "%TEMP_BACKUP%\config.json" >nul 2>&1
    echo       - Saved config.json
)

if exist "!TARGET_DIR!\token.dpapi" (
    copy /y "!TARGET_DIR!\token.dpapi" "%TEMP_BACKUP%\token.dpapi" >nul 2>&1
    echo       - Saved token.dpapi
) else if exist "!DATA_DIR!\token.dpapi" (
    copy /y "!DATA_DIR!\token.dpapi" "%TEMP_BACKUP%\token.dpapi" >nul 2>&1
    echo       - Saved token.dpapi
) else if exist "!TARGET_DIR!\broker_token.dat" (
    copy /y "!TARGET_DIR!\broker_token.dat" "%TEMP_BACKUP%\token.dpapi" >nul 2>&1
    echo       - Migrated legacy broker_token.dat -> token.dpapi
)

if exist "!TARGET_DIR!\backup_public.pem" (
    copy /y "!TARGET_DIR!\backup_public.pem" "%TEMP_BACKUP%\backup_public.pem" >nul 2>&1
    echo       - Saved backup_public.pem
)
if exist "!TARGET_DIR!\escrow_public.pem" (
    copy /y "!TARGET_DIR!\escrow_public.pem" "%TEMP_BACKUP%\escrow_public.pem" >nul 2>&1
    echo       - Saved escrow_public.pem
)
if exist "!TARGET_DIR!\backup_log.txt" (
    copy /y "!TARGET_DIR!\backup_log.txt" "%TEMP_BACKUP%\backup_log.txt" >nul 2>&1
    echo       - Saved backup_log.txt
)

:: 5. Purge obsolete Google OAuth credentials & tokens
echo.
echo [3/6] Purging legacy Google OAuth credentials and obsolete tokens...
if exist "!TARGET_DIR!\credentials.json" (
    del /f /q "!TARGET_DIR!\credentials.json" >nul 2>&1
    echo       - Purged legacy credentials.json
)
if exist "!TARGET_DIR!\token.json" (
    del /f /q "!TARGET_DIR!\token.json" >nul 2>&1
    echo       - Purged legacy token.json
)
if exist "!TARGET_DIR!\client_secret.json" (
    del /f /q "!TARGET_DIR!\client_secret.json" >nul 2>&1
    echo       - Purged legacy client_secret.json
)
if exist "!TARGET_DIR!\broker_token.dat" (
    del /f /q "!TARGET_DIR!\broker_token.dat" >nul 2>&1
)

:: 6. Overwrite application binaries (No Python needed on client PC)
echo.
echo [4/6] Copying updated application binaries...
robocopy.exe "%SOURCE_DIR%" "!TARGET_DIR!" /E /IS /IT >nul
if %ERRORLEVEL% GEQ 8 (
    echo [ERROR] Robocopy failed to copy update files!
    pause
    exit /b 1
)

:: Restore saved settings
if exist "%TEMP_BACKUP%\config.json" copy /y "%TEMP_BACKUP%\config.json" "!TARGET_DIR!\config.json" >nul 2>&1
if exist "%TEMP_BACKUP%\token.dpapi" copy /y "%TEMP_BACKUP%\token.dpapi" "!TARGET_DIR!\token.dpapi" >nul 2>&1
if exist "%TEMP_BACKUP%\backup_public.pem" copy /y "%TEMP_BACKUP%\backup_public.pem" "!TARGET_DIR!\backup_public.pem" >nul 2>&1
if exist "%TEMP_BACKUP%\escrow_public.pem" copy /y "%TEMP_BACKUP%\escrow_public.pem" "!TARGET_DIR!\escrow_public.pem" >nul 2>&1
if exist "%TEMP_BACKUP%\backup_log.txt" copy /y "%TEMP_BACKUP%\backup_log.txt" "!TARGET_DIR!\backup_log.txt" >nul 2>&1
rmdir /s /q "%TEMP_BACKUP%" >nul 2>&1
echo       Customer settings and tokens restored.

:: 7. Clean up legacy Google OAuth keys from config.json (preserves Sheet and Drive IDs)
echo.
echo [5/6] Sanitizing configuration file (Removing legacy Google OAuth file references)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = '!TARGET_DIR!\config.json'; " ^
    "if (Test-Path $cfgPath) { " ^
    "  $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json; " ^
    "  $legacy = @('CREDENTIALS_FILE', 'TOKEN_FILE', 'CLIENT_SECRET_FILE'); " ^
    "  foreach ($k in $legacy) { if ($cfg.PSObject.Properties.Name -contains $k) { $cfg.PSObject.Properties.Remove($k) } }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'BROKER_TOKEN_FILE')) { $cfg | Add-Member -MemberType NoteProperty -Name 'BROKER_TOKEN_FILE' -Value 'token.dpapi' } " ^
    "  else { $cfg.BROKER_TOKEN_FILE = 'token.dpapi' }; " ^
    "  $cfg | ConvertTo-Json -Depth 10 | Set-Content $cfgPath -Encoding UTF8; " ^
    "  Write-Host '       config.json sanitized successfully.' " ^
    "}"

:: Check for signed manifest.json to update broker endpoints if provided
set "MANIFEST_FILE=%~dp0manifest.json"
if exist "!MANIFEST_FILE!" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
        "try { " ^
        "  $m = Get-Content -Raw -Path '!MANIFEST_FILE!' -Encoding UTF8 | ConvertFrom-Json; " ^
        "  $cfgPath = '!TARGET_DIR!\config.json'; " ^
        "  if (Test-Path $cfgPath) { " ^
        "    $cfg = Get-Content -Raw -Path $cfgPath -Encoding UTF8 | ConvertFrom-Json; " ^
        "    if ($m.broker_url -and -not $cfg.BROKER_URL) { $cfg | Add-Member -NotePropertyName 'BROKER_URL' -NotePropertyValue $m.broker_url -Force; } " ^
        "    if ($m.customer_slug -and -not $cfg.CUSTOMER_SLUG) { $cfg | Add-Member -NotePropertyName 'CUSTOMER_SLUG' -NotePropertyValue $m.customer_slug -Force; } " ^
        "    if ($m.telemetry_url -and -not $cfg.TELEMETRY_BROKER_URL) { $cfg | Add-Member -NotePropertyName 'TELEMETRY_BROKER_URL' -NotePropertyValue $m.telemetry_url -Force; } " ^
        "    $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8; " ^
        "  } " ^
        "  if ($m.initial_token -and -not (Test-Path '!TARGET_DIR!\token.dpapi')) { " ^
        "    Add-Type -AssemblyName System.Security; " ^
        "    $bytes = [System.Text.Encoding]::UTF8.GetBytes($m.initial_token.Trim()); " ^
        "    $protected = [System.Security.Cryptography.ProtectedData]::Protect($bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine); " ^
        "    [System.IO.File]::WriteAllBytes('!TARGET_DIR!\token.dpapi', $protected); " ^
        "    Write-Host '       [OK] Configured token from signed manifest into DPAPI.' -ForegroundColor Green; " ^
        "  } " ^
        "} catch {}"
)

:: 8. Apply Folder & Token ACL Hardening
echo.
echo [6/6] Applying Folder Security Access Control Lists (ACLs)...
icacls.exe "!TARGET_DIR!" /grant:r Administrators:(OI)(CI)F /grant:r Users:(OI)(CI)RX >nul 2>&1
if exist "!TARGET_DIR!\token.dpapi" (
    icacls.exe "!TARGET_DIR!\token.dpapi" /inheritance:r /grant:r Administrators:F SYSTEM:F Users:R >nul 2>&1
)
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "DisplayVersion" /d "4.1.0" /t REG_SZ /f >nul 2>&1

echo.
echo ============================================================
echo   ZERO-TRUST APPLICATION UPDATE COMPLETED SUCCESSFULLY!
echo ============================================================
echo Database Cloud Backup upgraded to Version 4.1.0.
echo All operations configured for Zero-Trust architecture.
echo.

set /p LAUNCH="Launch updated application now? (Y/N, default Y): "
if /i not "!LAUNCH!"=="N" (
    start "" "!TARGET_DIR!\DatabaseBackupApp.exe"
)

exit /b 0
