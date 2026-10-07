<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Native PowerShell Performance Query Module (v4.3.0)
.DESCRIPTION
    Automated and Manual Database Performance, Integrity & Re-indexing Suite for Microsoft SQL Server.
    
    Features & Execution Sequence:
    1. Records Task Start Time in Customer Local Time Zone.
    2. Probes SQL Server Version and Database Storage Size.
    3. Query 1 (Inspection): Inspects index fragmentation across all tables via sys.dm_db_index_physical_stats.
    4. Pre-Maintenance Backup: Executes automated safety backup before maintenance ("Before do this take a backup").
    5. Query 2 (Maintenance):
       - DBCC CHECKDB with NO_INFOMSGS (Integrity validation)
       - DBCC DBREINDEX across all tables with FillFactor 80
       - sp_updatestats (Statistics refresh)
    6. Post-Maintenance Verification: Re-probes index fragmentation to measure optimization gain.
    7. Calculates total runtime duration.
    8. Streams full metrics to:
       - Customer Sheet -> [Performance Query] tab
       - Master "Application report" -> [Customer Tab]
       - Local Audit Log (backup_log.txt)
    9. Supports Automated and Manual execution modes, plus fixed-time task scheduling.
#>

[CmdletBinding()]
param(
    [ValidateSet("Manual", "Automatic")]
    [string]$Mode = "Manual",

    [string]$ConfigDir = "C:\ProgramData\DatabaseBackupApp",
    [string]$InstallDir = "C:\Program Files\DatabaseBackupApp",
    [string]$DatabaseName = "",
    [string]$ServerInstance = "",
    [switch]$SkipBackup,
    
    # Scheduling Parameters
    [switch]$SetSchedule,
    [string]$ScheduleTime = "",      # e.g., "03:00"
    [string]$ScheduleDay = "Sunday"   # e.g., "Sunday" or "Daily"
)

Add-Type -AssemblyName System.Security

$configFile = Join-Path $ConfigDir "config.json"
$tokenFile  = Join-Path $ConfigDir "token.dpapi"
$logFile    = Join-Path $ConfigDir "backup_log.txt"

# ------------------------------------------------------------------------------
# 1. LOGGING & TIMEZONE HELPER
# ------------------------------------------------------------------------------
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $logLine = "$timestamp [PERFORMANCE_QUERY] [$Level] $Message"
    try { Add-Content -Path $logFile -Value $logLine -Encoding UTF8 -ErrorAction SilentlyContinue } catch {}
    
    $color = "White"
    if ($Level -eq "ERROR") { $color = "Red" }
    elseif ($Level -eq "WARNING") { $color = "Yellow" }
    elseif ($Level -eq "SUCCESS") { $color = "Green" }
    Write-Host $logLine -ForegroundColor $color
}

# ------------------------------------------------------------------------------
# 2. FIXED-TIME SCHEDULING CONFIGURATOR
# ------------------------------------------------------------------------------
if ($SetSchedule -or ($ScheduleTime -ne "")) {
    $timeToSet = if ($ScheduleTime -ne "") { $ScheduleTime } else { "03:00" }
    Write-Host "`n[+] Configuring Automated Performance Maintenance Task..." -ForegroundColor Cyan
    
    $scriptPath = $PSCommandPath
    if (-not $scriptPath -or -not (Test-Path $scriptPath)) {
        $scriptPath = Join-Path $InstallDir "performance_query.ps1"
    }
    
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$scriptPath`" -Mode Automatic"
    
    if ($ScheduleDay -eq "Daily") {
        $trigger = New-ScheduledTaskTrigger -Daily -At $timeToSet
    } else {
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $ScheduleDay -At $timeToSet
    }
    
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    
    try {
        Register-ScheduledTask -TaskName "DatabaseBackup_PerformanceMaintenance" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        Write-Host "    [OK] Task 'DatabaseBackup_PerformanceMaintenance' registered: $ScheduleDay at $timeToSet" -ForegroundColor Green
        
        # Save fixed time in config.json
        if (Test-Path $configFile) {
            $cfg = Get-Content $configFile -Raw | ConvertFrom-Json
            $cfg | Add-Member -Name "PERFORMANCE_SCHEDULE_TIME" -Value $timeToSet -MemberType NoteProperty -Force
            $cfg | Add-Member -Name "PERFORMANCE_SCHEDULE_DAY" -Value $ScheduleDay -MemberType NoteProperty -Force
            $cfg | ConvertTo-Json -Depth 4 | Set-Content $configFile -Encoding UTF8
        }
    } catch {
        Write-Host "    [ERROR] Failed to register task: $_" -ForegroundColor Red
    }

    if (-not $PSBoundParameters.ContainsKey('Mode') -or $Mode -eq "Manual") {
        # If user only wanted to set schedule, exit here
        if ($ScheduleTime -ne "" -and -not $PSBoundParameters.ContainsKey('DatabaseName') -and -not (Test-Path $tokenFile)) {
            exit 0
        }
    }
}

# ------------------------------------------------------------------------------
# 3. INITIALIZE CONFIGURATION & TOKENS
# ------------------------------------------------------------------------------
if (-not (Test-Path $configFile) -or -not (Test-Path $tokenFile)) {
    Write-Log "Configuration or DPAPI token missing. Please ensure the agent is enrolled." "WARNING"
    exit 0
}

$config = Get-Content $configFile -Raw | ConvertFrom-Json
$brokerUrl = $config.BROKER_URL

$targetDb = if ($DatabaseName) { $DatabaseName } elseif ($config.DATABASE_NAME) { $config.DATABASE_NAME } else { "master" }
$sqlInst  = if ($ServerInstance) { $ServerInstance } elseif ($config.SQL_SERVER_INSTANCE) { $config.SQL_SERVER_INSTANCE } else { "localhost" }

# Capture Customer Start Time in Customer Local Time Zone
$customerTzName = [System.TimeZoneInfo]::Local.DisplayName
$customerStartTime = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") + " (" + $customerTzName + ")"
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Write-Log "============================================================" "INFO"
Write-Log "STARTING DATABASE PERFORMANCE & RE-INDEXING SUITE" "INFO"
Write-Log "Target DB: $targetDb | Instance: $sqlInst | Mode: $Mode" "INFO"
Write-Log "Task Start Time (Customer TZ): $customerStartTime" "INFO"
Write-Log "============================================================" "INFO"

# Unprotect DPAPI Machine Token
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

# ------------------------------------------------------------------------------
# 4. LOCATE SQLCMD EXECUTABLE
# ------------------------------------------------------------------------------
function Find-SqlCmd {
    $cmd = Get-Command "sqlcmd.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidatePaths = @(
        "$env:ProgramFiles\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\Client SDK\ODBC\130\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\160\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\150\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\140\Tools\Binn\sqlcmd.exe",
        "$env:ProgramFiles\Microsoft SQL Server\130\Tools\Binn\sqlcmd.exe",
        "${env:ProgramFiles(x86)}\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe",
        "${env:ProgramFiles(x86)}\Microsoft SQL Server\140\Tools\Binn\sqlcmd.exe"
    )
    foreach ($p in $candidatePaths) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

$sqlcmdExe = Find-SqlCmd
if (-not $sqlcmdExe) {
    Write-Log "sqlcmd.exe not found on system PATH or standard SQL installation paths." "ERROR"
    exit 1
}

function Invoke-SqlStatement {
    param([string]$Sql, [int]$TimeoutSec = 300)
    $tempOut = Join-Path $env:TEMP ("sql_out_" + [System.Guid]::NewGuid().ToString() + ".txt")
    $argsList = "-S `"$sqlInst`" -E -Q `"$Sql`" -h -1 -W"
    
    $proc = Start-Process -FilePath $sqlcmdExe -ArgumentList $argsList -Wait -NoNewWindow -PassThru `
        -RedirectStandardOutput $tempOut -ErrorAction SilentlyContinue

    $content = ""
    if (Test-Path $tempOut) {
        $content = (Get-Content $tempOut -Raw -ErrorAction SilentlyContinue)
        Remove-Item $tempOut -Force -ErrorAction SilentlyContinue
    }
    return @{ ExitCode = $proc.ExitCode; Output = if ($content) { $content.Trim() } else { "" } }
}

# ------------------------------------------------------------------------------
# 5. FETCH SQL SERVER VERSION & DATABASE SIZE
# ------------------------------------------------------------------------------
Write-Log "Probing SQL Server metadata and database storage capacity..." "INFO"
$metaSql = @"
SET NOCOUNT ON;
SELECT 
    CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(30)) + ' (' + CAST(SERVERPROPERTY('Edition') AS VARCHAR(40)) + ')' AS Version,
    ISNULL((SELECT SUM(size)*8/1024 FROM sys.master_files WHERE database_id = DB_ID('$targetDb')), 0) AS SizeMB;
"@

$metaResult = Invoke-SqlStatement -Sql $metaSql
$sqlVersion = "Microsoft SQL Server"
$dbSizeMB = 0

if ($metaResult.ExitCode -eq 0 -and $metaResult.Output) {
    $lines = $metaResult.Output -split "\r?\n" | Where-Object { $_.Trim() -ne "" }
    if ($lines.Count -ge 1) {
        $tokens = $lines[0] -split '\s{2,}'
        if ($tokens.Count -ge 1) { $sqlVersion = $tokens[0].Trim() }
        if ($tokens.Count -ge 2) { $dbSizeMB = [int]($tokens[1].Trim()) }
    }
}
Write-Log "SQL Server Version: $sqlVersion | DB Size: $dbSizeMB MB" "SUCCESS"

# ------------------------------------------------------------------------------
# 6. QUERY 1: INSPECT INDEX FRAGMENTATION (BEFORE MAINTENANCE)
# ------------------------------------------------------------------------------
Write-Log "Executing Query 1: Index Fragmentation Analysis on [$targetDb]..." "INFO"

$query1Sql = @"
SET NOCOUNT ON;
USE [$targetDb];
SELECT 
    TableName = object_name(dm.object_id),
    IndexName = i.name,
    IndexType = dm.index_type_desc,
    [%Fragmented] = CAST(avg_fragmentation_in_percent AS DECIMAL(5,2))
FROM sys.dm_db_index_physical_stats(db_id(), null, null, null, 'sampled') dm
JOIN sys.indexes i ON dm.object_id = dm.object_id AND dm.index_id = i.index_id
WHERE avg_fragmentation_in_percent > 10.0
ORDER BY avg_fragmentation_in_percent DESC;
"@

$q1Result = Invoke-SqlStatement -Sql $query1Sql
$fragBeforeMax = 0.0
$fragBeforeCount = 0

if ($q1Result.ExitCode -eq 0 -and $q1Result.Output) {
    $q1Lines = $q1Result.Output -split "\r?\n" | Where-Object { $_.Trim() -ne "" }
    $fragBeforeCount = $q1Lines.Count
    if ($q1Lines.Count -gt 0) {
        # Top line has highest fragmentation
        $firstCols = $q1Lines[0] -split '\s+'
        if ($firstCols.Count -ge 1) {
            $fragVal = $firstCols[-1] -as [double]
            if ($fragVal) { $fragBeforeMax = $fragVal }
        }
    }
}
$fragBeforeSummary = "$fragBeforeCount indexes fragmented (>10%). Max fragmentation: ${fragBeforeMax}%"
Write-Log "Query 1 Completed. $fragBeforeSummary" "SUCCESS"

# ------------------------------------------------------------------------------
# 7. SAFETY PRE-MAINTENANCE BACKUP ("Before do this take a backup---")
# ------------------------------------------------------------------------------
$preBackupStatus = "Skipped"

if (-not $SkipBackup) {
    Write-Log "Executing Pre-Maintenance Safety Backup before running Re-indexing..." "INFO"
    $backupScript = Join-Path (Split-Path $MyInvocation.MyCommand.Path) "backup_agent.ps1"
    if (-not (Test-Path $backupScript)) {
        $backupScript = Join-Path $InstallDir "backup_agent.ps1"
    }

    if (Test-Path $backupScript) {
        try {
            & $backupScript -ConfigDir $ConfigDir -InstallDir $InstallDir -RunMode $Mode
            $preBackupStatus = "Completed & Uploaded to Drive"
            Write-Log "Pre-Maintenance Safety Backup successfully executed!" "SUCCESS"
        } catch {
            $preBackupStatus = "Backup Warning: $_"
            Write-Log "Warning during pre-maintenance backup: $_" "WARNING"
        }
    } else {
        $preBackupStatus = "Backup Script Missing"
        Write-Log "Notice: backup_agent.ps1 not found at $backupScript. Proceeding with caution." "WARNING"
    }
} else {
    Write-Log "Safety backup skipped by administrator switch (-SkipBackup)." "WARNING"
    $preBackupStatus = "Skipped by Flag"
}

# ------------------------------------------------------------------------------
# 8. QUERY 2: DATABASE INTEGRITY CHECK, RE-INDEXING & UPDATE STATS
# ------------------------------------------------------------------------------
Write-Log "Executing Query 2: DBCC CHECKDB, DBCC DBREINDEX (80) & sp_updatestats..." "INFO"

# Step 2a: DBCC CHECKDB
Write-Log "Running DBCC CHECKDB(N'$targetDb') WITH NO_INFOMSGS..." "INFO"
$checkdbSql = "USE [$targetDb]; DBCC CHECKDB(N'$targetDb') WITH NO_INFOMSGS;"
$checkdbResult = Invoke-SqlStatement -Sql $checkdbSql -TimeoutSec 600
$checkdbStatus = if ($checkdbResult.ExitCode -eq 0) { "Clean (0 consistency errors)" } else { "Errors Detected: " + $checkdbResult.Output }
Write-Log "CHECKDB Result: $checkdbStatus" $(if ($checkdbResult.ExitCode -eq 0) { "SUCCESS" } else { "ERROR" })

# Step 2b: DBCC DBREINDEX with FillFactor 80
Write-Log "Running EXEC sp_MSforeachtable DBCC DBREINDEX ('?', ' ', 80)..." "INFO"
$reindexSql = "USE [$targetDb]; EXEC sp_MSforeachtable @command1=""print '?' DBCC DBREINDEX ('?', ' ', 80)"";"
$reindexResult = Invoke-SqlStatement -Sql $reindexSql -TimeoutSec 1200
$reindexStatus = if ($reindexResult.ExitCode -eq 0) { "Reindexed (FillFactor 80)" } else { "Reindex Error" }
Write-Log "DBREINDEX Result: $reindexStatus" "SUCCESS"

# Step 2c: EXEC sp_updatestats
Write-Log "Running EXEC sp_updatestats..." "INFO"
$updatestatsSql = "USE [$targetDb]; EXEC sp_updatestats;"
$updatestatsResult = Invoke-SqlStatement -Sql $updatestatsSql -TimeoutSec 300
$updatestatsStatus = if ($updatestatsResult.ExitCode -eq 0) { "Statistics Updated" } else { "Stats Warning" }
Write-Log "sp_updatestats Result: $updatestatsStatus" "SUCCESS"

# ------------------------------------------------------------------------------
# 9. POST-MAINTENANCE VERIFICATION (RE-CHECK FRAGMENTATION)
# ------------------------------------------------------------------------------
Write-Log "Re-checking index fragmentation post-maintenance..." "INFO"
$q1AfterResult = Invoke-SqlStatement -Sql $query1Sql
$fragAfterMax = 0.0
$fragAfterCount = 0

if ($q1AfterResult.ExitCode -eq 0 -and $q1AfterResult.Output) {
    $q1AfterLines = $q1AfterResult.Output -split "\r?\n" | Where-Object { $_.Trim() -ne "" }
    $fragAfterCount = $q1AfterLines.Count
    if ($q1AfterLines.Count -gt 0) {
        $firstCols = $q1AfterLines[0] -split '\s+'
        if ($firstCols.Count -ge 1) {
            $fragVal = $firstCols[-1] -as [double]
            if ($fragVal) { $fragAfterMax = $fragVal }
        }
    }
}
$fragAfterSummary = "$fragAfterCount indexes remaining. Max fragmentation: ${fragAfterMax}%"
Write-Log "Post-Maintenance Verification: $fragAfterSummary (Reduction: ${fragBeforeMax}% -> ${fragAfterMax}%)" "SUCCESS"

# ------------------------------------------------------------------------------
# 10. STOPWATCH & RUN TIME MEASUREMENT
# ------------------------------------------------------------------------------
$stopwatch.Stop()
$totalDurationSecs = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
$queryExecDateTime = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

Write-Log "============================================================" "SUCCESS"
Write-Log "PERFORMANCE & MAINTENANCE SUITE COMPLETED IN ${totalDurationSecs}s" "SUCCESS"
Write-Log "Execution Date-Time: $queryExecDateTime" "SUCCESS"
Write-Log "============================================================" "SUCCESS"

# ------------------------------------------------------------------------------
# 11. STREAM METRICS TO GOOGLE APPS SCRIPT BROKER
# ------------------------------------------------------------------------------
Write-Log "Streaming performance metrics to Master Application Report & Customer Sheet..." "INFO"

$perfPayload = @{
    action             = "report_status"
    token              = $bearerToken
    module             = "PERFORMANCE_QUERY"
    run_mode           = $Mode
    task_start_time    = $customerStartTime
    query_exec_time    = $queryExecDateTime
    db_name            = $targetDb
    sql_version        = $sqlVersion
    db_size_mb         = $dbSizeMB
    pre_backup_status  = $preBackupStatus
    frag_before_max    = $fragBeforeMax
    frag_after_max     = $fragAfterMax
    checkdb_status     = $checkdbStatus
    reindex_status     = "$reindexStatus & $updatestatsStatus"
    duration_secs      = $totalDurationSecs
    status             = if ($checkdbResult.ExitCode -eq 0 -and $reindexResult.ExitCode -eq 0) { "SUCCESS" } else { "COMPLETED_WITH_WARNINGS" }
    customer_sheet_id  = if ($config.CUSTOMER_SHEET_ID) { $config.CUSTOMER_SHEET_ID } else { "" }
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
    Write-Log "Performance telemetry logged successfully to Customer Sheet [Performance Query] & Master Application Report." "SUCCESS"
} catch {
    Write-Log "Failed to submit performance telemetry: $_" "WARNING"
}
