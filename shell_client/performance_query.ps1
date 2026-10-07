<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Native PowerShell Performance Query Module (v4.3.0)
.DESCRIPTION
    Database performance benchmark and DMV health monitor.
    - Executes non-blocking diagnostic query against target database.
    - Measures query response latency (ms), active connections, and database capacity.
    - Authenticates via DPAPI token and streams metrics to:
      1. Customer Sheet -> [Performance Query] tab
      2. Master "Application report" -> [Customer Tab]
      3. Local Audit Log (backup_log.txt)
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
    $logLine = "$timestamp [PERFORMANCE_QUERY] [$Level] $Message"
    try { Add-Content -Path $logFile -Value $logLine -Encoding UTF8 -ErrorAction SilentlyContinue } catch {}
    Write-Host $logLine
}

if (-not (Test-Path $configFile) -or -not (Test-Path $tokenFile)) {
    Write-Log "Configuration or DPAPI token missing. Aborting performance query." "WARNING"
    exit 0
}

$config = Get-Content $configFile -Raw | ConvertFrom-Json
$brokerUrl = $config.BROKER_URL
$dbEngine = if ($config.DATABASE_ENGINE) { $config.DATABASE_ENGINE } else { "MSSQL" }
$dbName = if ($config.DATABASE_NAME) { $config.DATABASE_NAME } else { "master" }
$sqlInstance = if ($config.SQL_SERVER_INSTANCE) { $config.SQL_SERVER_INSTANCE } else { "localhost" }

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

Write-Log "Initiating database performance diagnostic for $dbName ($dbEngine)..." "INFO"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$perfDetails = "Diagnostic query executed"
$connCount = 1
$dbSizeMB = 0

if ($dbEngine -eq "MSSQL") {
    $dmvSql = "SET NOCOUNT ON; SELECT (SELECT count(*) FROM sys.dm_exec_connections) AS Connections, ISNULL((SELECT SUM(size)*8/1024 FROM sys.master_files WHERE database_id = DB_ID('$dbName')), 0) AS SizeMB;"
    try {
        $proc = Start-Process -FilePath "sqlcmd.exe" -ArgumentList "-S `"$sqlInstance`" -E -Q `"$dmvSql`" -h -1 -W" -Wait -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $env:TEMP "perf_out.txt") -ErrorAction SilentlyContinue
        if ($proc.ExitCode -eq 0 -and (Test-Path (Join-Path $env:TEMP "perf_out.txt"))) {
            $rawOut = (Get-Content (Join-Path $env:TEMP "perf_out.txt") -Raw).Trim()
            $parts = $rawOut -split '\s+'
            if ($parts.Count -ge 2) {
                $connCount = [int]$parts[0]
                $dbSizeMB  = [int]$parts[1]
            }
            Remove-Item (Join-Path $env:TEMP "perf_out.txt") -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}

$sw.Stop()
$latencyMs = [math]::Max(1, $sw.ElapsedMilliseconds)
$perfDetails = "Active Connections: $connCount | DB Storage: $dbSizeMB MB | Query Latency: ${latencyMs}ms"

Write-Log "Performance benchmark completed in ${latencyMs}ms. Details: $perfDetails" "INFO"

# Stream metrics to Broker
$perfPayload = @{
    action            = "report_status"
    token             = $bearerToken
    module            = "PERFORMANCE_QUERY"
    run_mode          = $RunMode
    status            = "SUCCESS"
    db_name           = $dbName
    metric_name       = "SQL_DMV_HEALTH_CHECK"
    execution_ms      = $latencyMs
    duration_secs     = [math]::Round($latencyMs / 1000, 2)
    details           = $perfDetails
    customer_sheet_id = if ($config.CUSTOMER_SHEET_ID) { $config.CUSTOMER_SHEET_ID } else { "" }
}

$json = $perfPayload | ConvertTo-Json -Depth 4 -Compress
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
    Write-Log "Performance query telemetry logged to Customer Sheet [Performance Query] & Master Application Report." "INFO"
} catch {
    Write-Log "Failed to submit performance telemetry: $_" "WARNING"
}
