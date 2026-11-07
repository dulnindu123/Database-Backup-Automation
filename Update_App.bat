@echo off
setlocal enabledelayedexpansion

:: Check for Administrator privileges; auto-elevate if needed
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ELEVATION] Requesting Administrator Privileges...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

title Enterprise Database Cloud Backup - Zero-Trust In-Place Updater v5.0.0
color 0b

echo ============================================================
echo   ENTERPRISE DATABASE CLOUD BACKUP
echo   Zero-Trust In-Place Application Updater - v5.0.0
echo ============================================================
echo.
echo This tool safely upgrades Database Cloud Backup on client
echo servers and workstations to the v5.0 Enterprise Architecture.
echo.
echo ARCHITECTURE ENHANCEMENTS IN v5.0.0:
echo   - Externalized SQL Credentials: Reads SQLPara.txt / secrets.dat DPAPI.
echo   - Customer Escrow Key Isolation: escrow_public_{slug}.pem per customer.
echo   - Cloud Folder Routing: Direct to customer-dedicated Drive storage.
echo   - Enterprise Policy Enforcement: Automated alerts if encryption is disabled.
echo   - Intelligent Tiered Index Maintenance: <5%% Skip, 5-30%% Reorganize, >30%% Rebuild.
echo   - Daytime Protection: Index maintenance restricted to off-peak hours (19:00-07:00).
echo   - High-Throughput Upload Engine: Dynamic adaptive chunk sizing.
echo   - Token & ACL Hardening: Machine-scoped DPAPI vault with strict Windows ACLs.
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
    for /f "tokens=2*" %%A in ('reg.exe query "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "InstallLocation" 2^>nul') do (
        set "TARGET_DIR=%%B"
    )
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
taskkill.exe /F /IM Setup_DatabaseBackup.exe >nul 2>&1
ping 127.0.0.1 -n 2 >nul
echo       Active processes terminated.

:: 4. Safety Backup of customer database settings and credentials
echo.
echo [2/6] Safeguarding customer database configurations and credentials...
set "TEMP_BACKUP=%TEMP%\DB_Backup_Config_Safety_v5"
if exist "%TEMP_BACKUP%" rmdir /s /q "%TEMP_BACKUP%" >nul 2>&1
mkdir "%TEMP_BACKUP%"

if exist "!TARGET_DIR!\config.json" (
    copy /y "!TARGET_DIR!\config.json" "%TEMP_BACKUP%\config.json" >nul 2>&1
    echo       - Preserved config.json
) else if exist "!DATA_DIR!\config.json" (
    copy /y "!DATA_DIR!\config.json" "%TEMP_BACKUP%\config.json" >nul 2>&1
    echo       - Preserved config.json
)

if exist "!TARGET_DIR!\token.dpapi" (
    copy /y "!TARGET_DIR!\token.dpapi" "%TEMP_BACKUP%\token.dpapi" >nul 2>&1
    echo       - Preserved token.dpapi
) else if exist "!DATA_DIR!\token.dpapi" (
    copy /y "!DATA_DIR!\token.dpapi" "%TEMP_BACKUP%\token.dpapi" >nul 2>&1
    echo       - Preserved token.dpapi
) else if exist "!TARGET_DIR!\broker_token.dat" (
    copy /y "!TARGET_DIR!\broker_token.dat" "%TEMP_BACKUP%\token.dpapi" >nul 2>&1
    echo       - Migrated legacy broker_token.dat -> token.dpapi
)

if exist "!TARGET_DIR!\SQLPara.txt" (
    copy /y "!TARGET_DIR!\SQLPara.txt" "%TEMP_BACKUP%\SQLPara.txt" >nul 2>&1
    echo       - Preserved SQLPara.txt
) else if exist "!DATA_DIR!\SQLPara.txt" (
    copy /y "!DATA_DIR!\SQLPara.txt" "%TEMP_BACKUP%\SQLPara.txt" >nul 2>&1
    echo       - Preserved SQLPara.txt
)

if exist "!TARGET_DIR!\secrets.dat" (
    copy /y "!TARGET_DIR!\secrets.dat" "%TEMP_BACKUP%\secrets.dat" >nul 2>&1
    echo       - Preserved secrets.dat
)

if exist "!TARGET_DIR!\backup_public.pem" (
    copy /y "!TARGET_DIR!\backup_public.pem" "%TEMP_BACKUP%\backup_public.pem" >nul 2>&1
    echo       - Preserved backup_public.pem
)
for %%F in ("!TARGET_DIR!\escrow_public*.pem") do (
    copy /y "%%F" "%TEMP_BACKUP%\" >nul 2>&1
    echo       - Preserved %%~nxF
)
if exist "!TARGET_DIR!\bundle.json" (
    copy /y "!TARGET_DIR!\bundle.json" "%TEMP_BACKUP%\bundle.json" >nul 2>&1
    echo       - Preserved bundle.json
)
if exist "!TARGET_DIR!\backup_log.txt" (
    copy /y "!TARGET_DIR!\backup_log.txt" "%TEMP_BACKUP%\backup_log.txt" >nul 2>&1
    echo       - Preserved backup_log.txt
)

:: 5. Purge obsolete Google OAuth credentials & legacy files
echo.
echo [3/6] Purging legacy Google OAuth credentials and obsolete files...
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

:: 6. Overwrite application binaries with v5.0.0
echo.
echo [4/6] Copying updated v5.0.0 application binaries...
robocopy.exe "%SOURCE_DIR%" "!TARGET_DIR!" /E /IS /IT >nul
if %ERRORLEVEL% GEQ 8 (
    echo [ERROR] Robocopy failed to copy update files!
    pause
    exit /b 1
)

:: Restore saved settings and credentials
if exist "%TEMP_BACKUP%\config.json" copy /y "%TEMP_BACKUP%\config.json" "!TARGET_DIR!\config.json" >nul 2>&1
if exist "%TEMP_BACKUP%\token.dpapi" copy /y "%TEMP_BACKUP%\token.dpapi" "!TARGET_DIR!\token.dpapi" >nul 2>&1
if exist "%TEMP_BACKUP%\SQLPara.txt" copy /y "%TEMP_BACKUP%\SQLPara.txt" "!TARGET_DIR!\SQLPara.txt" >nul 2>&1
if exist "%TEMP_BACKUP%\secrets.dat" copy /y "%TEMP_BACKUP%\secrets.dat" "!TARGET_DIR!\secrets.dat" >nul 2>&1
if exist "%TEMP_BACKUP%\backup_public.pem" copy /y "%TEMP_BACKUP%\backup_public.pem" "!TARGET_DIR!\backup_public.pem" >nul 2>&1
for %%F in ("%TEMP_BACKUP%\escrow_public*.pem") do (
    copy /y "%%F" "!TARGET_DIR!\" >nul 2>&1
)
if exist "%TEMP_BACKUP%\bundle.json" copy /y "%TEMP_BACKUP%\bundle.json" "!TARGET_DIR!\bundle.json" >nul 2>&1
if exist "%TEMP_BACKUP%\backup_log.txt" copy /y "%TEMP_BACKUP%\backup_log.txt" "!TARGET_DIR!\backup_log.txt" >nul 2>&1
rmdir /s /q "%TEMP_BACKUP%" >nul 2>&1
echo       Customer settings, keys, and tokens restored.

:: Copy build_info.json if present
if exist "%~dp0build_info.json" (
    copy /y "%~dp0build_info.json" "!TARGET_DIR!\build_info.json" >nul 2>&1
)

:: 7. Upgrade config.json to v5.0.0 Schema
echo.
echo [5/6] Upgrading configuration file to v5.0.0 Schema...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = '!TARGET_DIR!\config.json'; " ^
    "if (Test-Path $cfgPath) { " ^
    "  $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json; " ^
    "  $legacy = @('CREDENTIALS_FILE', 'TOKEN_FILE', 'CLIENT_SECRET_FILE'); " ^
    "  foreach ($k in $legacy) { if ($cfg.PSObject.Properties.Name -contains $k) { $cfg.PSObject.Properties.Remove($k) } }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'BROKER_TOKEN_FILE')) { $cfg | Add-Member -MemberType NoteProperty -Name 'BROKER_TOKEN_FILE' -Value 'token.dpapi' } " ^
    "  else { $cfg.BROKER_TOKEN_FILE = 'token.dpapi' }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'SQLPARA_PATH')) { $cfg | Add-Member -MemberType NoteProperty -Name 'SQLPARA_PATH' -Value 'SQLPara.txt' }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'ENFORCE_ENCRYPTION_POLICY')) { $cfg | Add-Member -MemberType NoteProperty -Name 'ENFORCE_ENCRYPTION_POLICY' -Value $false }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'ALERT_ON_ENCRYPTION_DISABLED')) { $cfg | Add-Member -MemberType NoteProperty -Name 'ALERT_ON_ENCRYPTION_DISABLED' -Value $true }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'MAINTENANCE_ALLOWED_START_HOUR')) { $cfg | Add-Member -MemberType NoteProperty -Name 'MAINTENANCE_ALLOWED_START_HOUR' -Value 19 }; " ^
    "  if (-not ($cfg.PSObject.Properties.Name -contains 'MAINTENANCE_ALLOWED_END_HOUR')) { $cfg | Add-Member -MemberType NoteProperty -Name 'MAINTENANCE_ALLOWED_END_HOUR' -Value 7 }; " ^
    "  $cfg | ConvertTo-Json -Depth 10 | Set-Content $cfgPath -Encoding UTF8; " ^
    "  Write-Host '       [OK] config.json upgraded with v5.0 schema defaults.' -ForegroundColor Green; " ^
    "}"

:: 7b. Synchronize Windows Task Scheduler with active configuration
echo.
echo [5b/6] Synchronizing Windows Task Scheduler with active configuration...
schtasks /delete /tn "DatabaseBackup_AutomatedTask" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_Daily" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_StorageMonitor" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_StorageCleanup" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackup_PerformanceMaintenance" /f >nul 2>&1
schtasks /delete /tn "DatabaseBackupApp" /f >nul 2>&1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$cfgPath = '!DATA_DIR!\config.json'; if (-not (Test-Path $cfgPath)) { $cfgPath = '!TARGET_DIR!\config.json' }; " ^
    "if (Test-Path $cfgPath) { " ^
    "  $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json; " ^
    "  $timeStr = if ($cfg.SCHEDULE_TIME) { $cfg.SCHEDULE_TIME } else { '02:00' }; " ^
    "  $exePath = '!TARGET_DIR!\DatabaseBackupApp.exe'; " ^
    "  $action = New-ScheduledTaskAction -Execute $exePath -Argument '--auto'; " ^
    "  $days = if ($cfg.SCHEDULE_DAYS) { $cfg.SCHEDULE_DAYS } else { @('MON') }; " ^
    "  $pwDays = @(); " ^
    "  $dayMap = @{ 'MON'='Monday'; 'TUE'='Tuesday'; 'WED'='Wednesday'; 'THU'='Thursday'; 'FRI'='Friday'; 'SAT'='Saturday'; 'SUN'='Sunday' }; " ^
    "  foreach ($d in $days) { if ($dayMap.ContainsKey($d)) { $pwDays += $dayMap[$d] } }; " ^
    "  if ($pwDays.Count -eq 0) { $pwDays = @('Monday') }; " ^
    "  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $pwDays -At $timeStr; " ^
    "  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 12); " ^
    "  Register-ScheduledTask -TaskName 'Database Cloud Backup' -Action $action -Trigger $trigger -Settings $settings -User 'NT AUTHORITY\SYSTEM' -RunLevel Highest -Force | Out-Null; " ^
    "  Write-Host '       [OK] Task Scheduler synchronized (Runs as NT AUTHORITY\SYSTEM at ' $timeStr ')' -ForegroundColor Green; " ^
    "} else { Write-Host '       [NOTICE] config.json not found; Task Scheduler retained.' -ForegroundColor Yellow }"

:: 8. Apply Folder & Token ACL Hardening
echo.
echo [6/6] Applying Folder Security Access Control Lists (ACLs)...
icacls.exe "!TARGET_DIR!" /grant:r Administrators:(OI)(CI)F /grant:r Users:(OI)(CI)RX >nul 2>&1
if exist "!TARGET_DIR!\token.dpapi" (
    icacls.exe "!TARGET_DIR!\token.dpapi" /inheritance:r /grant:r Administrators:F SYSTEM:F Users:R >nul 2>&1
)
reg.exe add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "DisplayVersion" /d "5.0.0" /t REG_SZ /f >nul 2>&1
reg.exe add "HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp" /v "DisplayVersion" /d "5.0.0" /t REG_SZ /f >nul 2>&1

echo.
echo ============================================================
echo   ZERO-TRUST APPLICATION UPGRADE COMPLETED SUCCESSFULLY!
echo ============================================================
echo Database Cloud Backup upgraded to Version 5.0.0.
echo All operations configured for v5.0 Enterprise Architecture.
echo.

set /p LAUNCH="Launch updated application now? (Y/N, default Y): "
if /i not "!LAUNCH!"=="N" (
    start "" "!TARGET_DIR!\DatabaseBackupApp.exe"
)

exit /b 0
