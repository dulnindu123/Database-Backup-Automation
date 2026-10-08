<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Native PowerShell Installer (v4.2.0)
.DESCRIPTION
    Zero-dependency, 100% native Windows PowerShell agent installer.
    - Requires NO Python, NO compiled .exe, and NO external package managers.
    - Uses Windows built-in .NET Cryptography & Windows DPAPI (LocalMachine scope).
    - Enrolls with the Google Apps Script Upload Broker.
    - Automatically configures Windows Scheduled Tasks for unattended execution.
.PARAMETER BundlePath
    Path to the signed bundle.json configuration envelope (default: bundle.json in current directory).
.PARAMETER BackupFolder
    Local staging folder for temporary database dumps (default: C:\SQLBackups).
.PARAMETER DatabaseEngine
    Database engine: MSSQL, MYSQL, or POSTGRES (default: MSSQL).
.PARAMETER DatabaseName
    Target database name (default: master).
.PARAMETER ServerInstance
    Database server/instance (default: localhost).
#>

[CmdletBinding()]
param(
    [string]$BundlePath = "bundle.json",
    [string]$InstallDir = "C:\Program Files\DatabaseBackupApp",
    [string]$DataDir    = "C:\ProgramData\DatabaseBackupApp",
    [string]$BackupFolder = "C:\SQLBackups",
    [string]$DatabaseEngine = "MSSQL",
    [string]$DatabaseName = "",
    [string]$ServerInstance = "localhost",
    [string]$PerformanceScheduleTime = "03:30",
    [string]$PerformanceScheduleDay  = "Sunday"
)

# ------------------------------------------------------------------------------
# 1. ELEVATION CHECK
# ------------------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "[FATAL] Administrator privileges required. Please re-run PowerShell as Administrator."
    exit 1
}

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  ENTERPRISE DATABASE CLOUD BACKUP - NATIVE POWERSHELL INSTALLER (v4.2.0)" -ForegroundColor Cyan
Write-Host "  Zero-Trust Architecture - 100% Native Windows Shell Agent (No Python Required)" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# ------------------------------------------------------------------------------
# 2. LOAD ASSEMBLIES & SECURITY PROTOCOLS
# ------------------------------------------------------------------------------
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.IO.Compression.FileSystem

[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls11 -bor [System.Net.SecurityProtocolType]::Tls

# ------------------------------------------------------------------------------
# 3. HELPER: APPS SCRIPT HTTP CLIENT (Handles 302 Redirect to Echo Service)
# ------------------------------------------------------------------------------
function Invoke-AppsScriptBroker {
    param(
        [string]$Url,
        [hashtable]$Payload,
        [int]$TimeoutSec = 30
    )
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12 -bor [System.Net.SecurityProtocolType]::Tls11 -bor [System.Net.SecurityProtocolType]::Tls

    $json = $Payload | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

    $req = [System.Net.HttpWebRequest]::Create($Url)
    $req.Method = "POST"
    $req.ContentType = "application/json; charset=utf-8"
    $req.AllowAutoRedirect = $false
    $req.Timeout = $TimeoutSec * 1000
    $req.ContentLength = $bytes.Length

    $stream = $req.GetRequestStream()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close()

    $resp = $null
    try {
        $resp = $req.GetResponse()
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if (-not $resp) {
            throw "Connection failed to broker endpoint ($Url): $($_.Exception.Message)"
        }
    } catch {
        throw "Unexpected network error ($Url): $_"
    }

    if (-not $resp) {
        throw "No response received from Upload Broker ($Url)."
    }

    $location = $null
    if ($resp.Headers -and $resp.Headers["Location"]) {
        $location = $resp.Headers["Location"]
    }

    if ($location) {
        # Follow 302 redirect via GET to download ContentService JSON output
        $getReq = [System.Net.HttpWebRequest]::Create($location)
        $getReq.Method = "GET"
        $getReq.Timeout = $TimeoutSec * 1000
        $getResp = $getReq.GetResponse()
        $sr = New-Object System.IO.StreamReader($getResp.GetResponseStream())
        $content = $sr.ReadToEnd()
        $sr.Close()
        return ($content | ConvertFrom-Json)
    }

    $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
    $content = $sr.ReadToEnd()
    $sr.Close()
    if (-not $content) {
        throw "Broker returned empty response ($Url)"
    }
    return ($content | ConvertFrom-Json)
}

# ------------------------------------------------------------------------------
# 4. LOAD CONFIGURATION / BUNDLE
# ------------------------------------------------------------------------------
$brokerUrl = ""
$customerSlug = ""
$enrollCode = ""

if (Test-Path $BundlePath) {
    Write-Host "[+] Reading configuration from: $BundlePath" -ForegroundColor Green
    try {
        $bundle = Get-Content $BundlePath -Raw | ConvertFrom-Json
        $brokerUrl    = $bundle.broker_url
        $customerSlug = $bundle.customer_slug
        $enrollCode   = $bundle.enroll_code
    } catch {
        Write-Warning "[-] Could not parse bundle.json: $_"
    }
} else {
    $localCfgPath = Join-Path $PSScriptRoot "config.json"
    if (Test-Path $localCfgPath) {
        try {
            $localCfg = Get-Content $localCfgPath -Raw | ConvertFrom-Json
            if ($localCfg.BROKER_URL) { $brokerUrl = $localCfg.BROKER_URL.Trim() }
            if ($localCfg.CUSTOMER_SLUG) { $customerSlug = $localCfg.CUSTOMER_SLUG.Trim().ToLower() }
            if ($localCfg.ENROLL_CODE) { $enrollCode = $localCfg.ENROLL_CODE.Trim() }
            if ($localCfg.DATABASE_NAME -and -not $DatabaseName) { $DatabaseName = $localCfg.DATABASE_NAME }
            if ($localCfg.DATABASE_ENGINE -and ($DatabaseEngine -eq "MSSQL")) { $DatabaseEngine = $localCfg.DATABASE_ENGINE }
            if ($localCfg.SQL_SERVER_INSTANCE -and ($ServerInstance -eq "localhost")) { $ServerInstance = $localCfg.SQL_SERVER_INSTANCE }
            if ($localCfg.BACKUP_FOLDER -and ($BackupFolder -eq "C:\Backups\Staging")) { $BackupFolder = $localCfg.BACKUP_FOLDER }
            if ($localCfg.PERFORMANCE_SCHEDULE_DAY -and ($PerformanceScheduleDay -eq "Sunday")) { $PerformanceScheduleDay = $localCfg.PERFORMANCE_SCHEDULE_DAY }
            if ($localCfg.PERFORMANCE_SCHEDULE_TIME -and ($PerformanceScheduleTime -eq "03:30")) { $PerformanceScheduleTime = $localCfg.PERFORMANCE_SCHEDULE_TIME }
            Write-Host "[+] Loaded initial parameters from local config.json" -ForegroundColor Green
        } catch {
            Write-Warning "[-] Could not parse local config.json: $_"
        }
    }
}

if (-not $brokerUrl) {
    $brokerUrl = Read-Host "Enter Google Apps Script Web App URL (ends with /exec)"
}
if (-not $customerSlug) {
    $customerSlug = Read-Host "Enter Customer Short Name / Slug (e.g. acme)"
}
if (-not $enrollCode) {
    $enrollCode = Read-Host "Enter Enrollment Secret Code (ENROLL_CODE from sheet)"
}

$brokerUrl = $brokerUrl.Trim()
$customerSlug = $customerSlug.Trim().ToLower()
$enrollCode = $enrollCode.Trim()

if (-not $brokerUrl.StartsWith("https://script.google.com/macros/s/")) {
    Write-Error "[FATAL] Invalid Broker URL. Must be an official Google Apps Script endpoint (https://script.google.com/macros/s/.../exec)"
    exit 1
}

# ------------------------------------------------------------------------------
# 5. HARDWARE FINGERPRINTING & MACHINE IDENTITY
# ------------------------------------------------------------------------------
Write-Host "[+] Computing hardware fingerprint..." -ForegroundColor Yellow
$hostname = $env:COMPUTERNAME.ToLower()
$uuid = (Get-CimInstance Win32_ComputerSystemProduct).UUID
$cpu  = (Get-CimInstance Win32_Processor | Select-Object -First 1).ProcessorId
$mac  = (Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled } | Select-Object -First 1).MACAddress

$rawId = "$uuid-$cpu-$mac"
$sha256 = [System.Security.Cryptography.SHA256]::Create()
$hashBytes = $sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($rawId))
$hashHex = [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLower()

$pcId = "pc-$customerSlug-$($hashHex.Substring(0, 8))"
Write-Host "    PC Identifier: $pcId" -ForegroundColor Cyan

# Generate a high-entropy 256-bit machine secret
$rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
$secretBytes = New-Object byte[] 32
$rng.GetBytes($secretBytes)
$machineSecret = [System.BitConverter]::ToString($secretBytes).Replace("-", "").ToLower()
$fullToken = "$pcId.$machineSecret"

# ------------------------------------------------------------------------------
# 6. ENROLL WITH APPS SCRIPT BROKER
# ------------------------------------------------------------------------------
Write-Host "[+] Contacting Upload Broker for one-time enrollment..." -ForegroundColor Yellow
$enrollPayload = @{
    action        = "enroll"
    enroll_code   = $enrollCode
    pc_id         = $pcId
    customer_slug = $customerSlug
    token         = $fullToken
}

try {
    $enrollResult = Invoke-AppsScriptBroker -Url $brokerUrl -Payload $enrollPayload
    if ($enrollResult.error) {
        Write-Error "[FATAL] Broker rejected enrollment: $($enrollResult.error) (Code: $($enrollResult.code))"
        exit 1
    }
    $offsetMinutes = [int]$enrollResult.offset_minutes
    if (-not $offsetMinutes) { $offsetMinutes = 10 }
    Write-Host "    [OK] Machine Enrolled! Stagger Offset: $offsetMinutes minutes." -ForegroundColor Green
} catch {
    Write-Error "[FATAL] Failed to connect to broker: $_"
    exit 1
}

# ------------------------------------------------------------------------------
# 7. SEAL TOKEN INTO WINDOWS DPAPI VAULT
# ------------------------------------------------------------------------------
Write-Host "[+] Sealing token into Windows DPAPI machine-scope vault..." -ForegroundColor Yellow
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

$tokenBytes = [System.Text.Encoding]::UTF8.GetBytes($fullToken)
$dpapiCipher = [System.Security.Cryptography.ProtectedData]::Protect(
    $tokenBytes,
    $null,
    [System.Security.Cryptography.DataProtectionScope]::LocalMachine
)
$dpapiPath = Join-Path $DataDir "token.dpapi"
[System.IO.File]::WriteAllBytes($dpapiPath, $dpapiCipher)
Write-Host "    [OK] Sealed token at: $dpapiPath" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 8. INSTALL SCRIPT ASSETS & CONFIGURATION
# ------------------------------------------------------------------------------
Write-Host "[+] Installing PowerShell agent scripts to: $InstallDir" -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
if (-not (Test-Path $BackupFolder)) {
    New-Item -ItemType Directory -Path $BackupFolder -Force | Out-Null
}

$currentScriptDir = $PSScriptRoot
$filesToCopy = @("backup_agent.ps1", "storage_monitor.ps1", "performance_query.ps1", "run_automation.ps1", "uninstall_agent.ps1", "backup_public.pem", "escrow_public.pem")

foreach ($f in $filesToCopy) {
    $src = Join-Path $currentScriptDir $f
    if (-not (Test-Path $src)) {
        # Check parent folder or AppFiles
        $alt1 = Join-Path (Join-Path $currentScriptDir "..") $f
        $alt2 = Join-Path (Join-Path $currentScriptDir "..\AppFiles") $f
        if (Test-Path $alt1) { $src = $alt1 }
        elseif (Test-Path $alt2) { $src = $alt2 }
    }
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $InstallDir $f) -Force
        Write-Host "    Copied: $f" -ForegroundColor DarkGray
    }
}

# Write config.json
$config = @{
    BROKER_URL             = $brokerUrl
    CUSTOMER_SLUG          = $customerSlug
    BACKUP_FOLDER          = $BackupFolder
    DATABASE_ENGINE        = $DatabaseEngine
    DATABASE_NAME          = $DatabaseName
    SQL_SERVER_INSTANCE    = $ServerInstance
    OFFSET_MINUTES             = $offsetMinutes
    PRIMARY_PUBLIC_KEY         = "backup_public.pem"
    ESCROW_PUBLIC_KEY          = "escrow_public.pem"
    PERFORMANCE_SCHEDULE_TIME  = $PerformanceScheduleTime
    PERFORMANCE_SCHEDULE_DAY   = $PerformanceScheduleDay
}
$configPath = Join-Path $DataDir "config.json"
$config | ConvertTo-Json -Depth 4 | Set-Content $configPath -Encoding UTF8
Write-Host "    [OK] Configuration written to: $configPath" -ForegroundColor Green

# Restrict ACLs with icacls
& icacls.exe $DataDir /inheritance:r /grant "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" >$null 2>&1
& icacls.exe $InstallDir /inheritance:r /grant "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" >$null 2>&1

# ------------------------------------------------------------------------------
# 9. CONFIGURE WINDOWS TASK SCHEDULER
# ------------------------------------------------------------------------------
Write-Host "[+] Registering Windows Scheduled Tasks..." -ForegroundColor Yellow

$backupScript  = Join-Path $InstallDir "backup_agent.ps1"
$monitorScript = Join-Path $InstallDir "storage_monitor.ps1"
$perfScript    = Join-Path $InstallDir "performance_query.ps1"

# Compute staggered time (e.g., 02:00 AM + offset minutes)
$baseHour = 2
$baseMinute = $offsetMinutes
$taskTime = "{0:D2}:{1:D2}" -f $baseHour, $baseMinute

# Task 1: Daily Backup
$action1 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$backupScript`""
$trigger1 = New-ScheduledTaskTrigger -Daily -At $taskTime
$principal1 = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "DatabaseBackup_AutomatedTask" -Action $action1 -Trigger $trigger1 -Principal $principal1 -Settings $settings1 -Force | Out-Null
Write-Host "    [OK] Scheduled Task registered: 'DatabaseBackup_AutomatedTask' (Daily at $taskTime)" -ForegroundColor Green

# Task 2: Storage Monitor (Hourly)
$action2 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$monitorScript`""
$trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "DatabaseBackup_StorageMonitor" -Action $action2 -Trigger $trigger2 -Principal $principal1 -Settings $settings1 -Force | Out-Null
Write-Host "    [OK] Scheduled Task registered: 'DatabaseBackup_StorageMonitor' (Hourly)" -ForegroundColor Green

# Task 3: Performance Maintenance & Re-indexing (Fixed Time: e.g. Sunday at 03:30 AM or Daily)
$action3 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$perfScript`" -Mode Automatic"
if ($PerformanceScheduleDay -eq "Daily") {
    $trigger3 = New-ScheduledTaskTrigger -Daily -At $PerformanceScheduleTime
} else {
    $trigger3 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $PerformanceScheduleDay -At $PerformanceScheduleTime
}
Register-ScheduledTask -TaskName "DatabaseBackup_PerformanceMaintenance" -Action $action3 -Trigger $trigger3 -Principal $principal1 -Settings $settings1 -Force | Out-Null
Write-Host "    [OK] Scheduled Task registered: 'DatabaseBackup_PerformanceMaintenance' ($PerformanceScheduleDay at $PerformanceScheduleTime)" -ForegroundColor Green

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  INSTALLATION COMPLETE! Native PowerShell Agent is fully configured." -ForegroundColor Green
Write-Host "  To run a manual test backup right now, execute:" -ForegroundColor White
Write-Host "    powershell.exe -ExecutionPolicy Bypass -File `"$backupScript`"" -ForegroundColor Yellow
Write-Host "  To cleanly uninstall this agent in the future, execute:" -ForegroundColor White
Write-Host "    powershell.exe -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'uninstall_agent.ps1')`"" -ForegroundColor Yellow
Write-Host "================================================================================" -ForegroundColor Cyan
