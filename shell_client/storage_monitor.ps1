<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Native PowerShell Storage Monitor (v4.2.0)
.DESCRIPTION
    Hourly background storage telemetry monitor for Windows servers.
    - Evaluates all fixed local drives.
    - Collects total capacity, free space, and usage percentage.
    - Authenticates via DPAPI token and logs telemetry to Master Google Sheet.
#>

[CmdletBinding()]
param(
    [string]$ConfigDir = "C:\ProgramData\DatabaseBackupApp",
    [string]$RunMode = "Automatic"
)

Add-Type -AssemblyName System.Security

$configFile = Join-Path $ConfigDir "config.json"
$tokenFile  = Join-Path $ConfigDir "token.dpapi"
$logFile    = Join-Path $ConfigDir "backup_log.txt"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $logLine = "$timestamp [STORAGE_MONITOR] [$Level] $Message"
    try { Add-Content -Path $logFile -Value $logLine -Encoding UTF8 -ErrorAction SilentlyContinue } catch {}
}

if (-not (Test-Path $configFile) -or -not (Test-Path $tokenFile)) {
    exit 0
}

$config = Get-Content $configFile -Raw | ConvertFrom-Json
$brokerUrl = $config.BROKER_URL

# Unprotect DPAPI token
try {
    $dpapiBytes = [System.IO.File]::ReadAllBytes($tokenFile)
    $unprotected = [System.Security.Cryptography.ProtectedData]::Unprotect(
        $dpapiBytes,
        $null,
        [System.Security.Cryptography.DataProtectionScope]::LocalMachine
    )
    $bearerToken = [System.Text.Encoding]::UTF8.GetString($unprotected)
} catch {
    Write-Log "Failed to unprotect DPAPI token: $_" "ERROR"
    exit 1
}

# Scan fixed storage drives
$drives = Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 }
$diskMetrics = @()

foreach ($d in $drives) {
    $totalGB = [math]::Round($d.Size / 1GB, 2)
    $freeGB  = [math]::Round($d.FreeSpace / 1GB, 2)
    $usedPct = [math]::Round((($d.Size - $d.FreeSpace) / $d.Size) * 100, 1)

    $diskMetrics += @{
        drive_letter = $d.DeviceID
        total_gb     = $totalGB
        free_gb      = $freeGB
        used_percent = $usedPct
    }
}

Write-Log "Collected storage telemetry across $($drives.Count) drives." "INFO"

# Send telemetry to broker
$telemetryPayload = @{
    action            = "report_status"
    token             = $bearerToken
    module            = "SERVER_CLEANUP"
    run_mode          = $RunMode
    status            = "SUCCESS"
    db_name           = "DISK_HEALTH"
    file_name         = "STORAGE_TELEMETRY"
    bytes             = 0
    sha256            = "STORAGE_PROBE"
    duration_secs     = 1
    metrics           = $diskMetrics
    customer_sheet_id = if ($config.CUSTOMER_SHEET_ID) { $config.CUSTOMER_SHEET_ID } else { "" }
}

$json = $telemetryPayload | ConvertTo-Json -Depth 4 -Compress
$bytes = [System.Text.Encoding]::UTF8.GetBytes($json)

$req = [System.Net.HttpWebRequest]::Create($brokerUrl)
$req.Method = "POST"
$req.ContentType = "application/json; charset=utf-8"
$req.AllowAutoRedirect = $false
$req.ContentLength = $bytes.Length

$stream = $req.GetRequestStream()
$stream.Write($bytes, 0, $bytes.Length)
$stream.Close()

try {
    $resp = $req.GetResponse()
    Write-Log "Storage telemetry submitted to Master Google Sheet." "INFO"
} catch {
    Write-Log "Failed to submit storage telemetry: $_" "WARNING"
}
