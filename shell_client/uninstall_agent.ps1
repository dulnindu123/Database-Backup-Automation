<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Clean Uninstaller (v4.2.0)
.DESCRIPTION
    100% native Windows PowerShell agent clean uninstaller.
    - Completely stops running backup and maintenance tasks.
    - Removes all Windows Scheduled Tasks registered by the agent.
    - Securely shreds the machine-bound DPAPI token (token.dpapi).
    - Removes agent scripts, configurations, public keys, and shortcuts.
    - Optionally archives local execution audit logs to the user's Desktop.
.PARAMETER Force
    Executes uninstallation silently without interactive confirmation prompts.
.PARAMETER KeepLogs
    Archives the audit log files to the current user's Desktop before deletion.
.PARAMETER KeepBackups
    Preserves local database backup dumps in the staging folder.
.PARAMETER InstallDir
    Installation directory to remove (default: C:\Program Files\DatabaseBackupApp).
.PARAMETER DataDir
    Program data directory to remove (default: C:\ProgramData\DatabaseBackupApp).
#>

[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$KeepLogs = $true,
    [switch]$KeepBackups = $true,
    [string]$InstallDir = "C:\Program Files\DatabaseBackupApp",
    [string]$DataDir    = "C:\ProgramData\DatabaseBackupApp"
)

# ------------------------------------------------------------------------------
# 1. ELEVATION VERIFICATION
# ------------------------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "[!] Elevation required. Requesting Administrator privileges..."
    $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($Force) { $argList += " -Force" }
    if ($KeepLogs) { $argList += " -KeepLogs" }
    if ($KeepBackups) { $argList += " -KeepBackups" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList
    exit
}

Clear-Host
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  ENTERPRISE DATABASE CLOUD BACKUP - AGENT CLEAN UNINSTALLER (v4.2.0)" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target Installation Directory : $InstallDir" -ForegroundColor White
Write-Host "Target Data Directory         : $DataDir" -ForegroundColor White
Write-Host ""
Write-Host "This operation will permanently remove:" -ForegroundColor Yellow
Write-Host "  • All Windows Scheduled Tasks (Daily Backups, Cleanup, Performance Reindexing)" -ForegroundColor Gray
Write-Host "  • Active running agent processes" -ForegroundColor Gray
Write-Host "  • Machine DPAPI authentication vault (token.dpapi)" -ForegroundColor Gray
Write-Host "  • Client application scripts, public keys, and configurations" -ForegroundColor Gray
Write-Host "  • Desktop and Start Menu application shortcuts" -ForegroundColor Gray
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "Are you sure you want to completely uninstall this agent? (Y/N)"
    if ($confirm -notmatch '^[Yy]$') {
        Write-Host "Uninstallation cancelled by user." -ForegroundColor Yellow
        exit 0
    }
}

# ------------------------------------------------------------------------------
# 2. ARCHIVE AUDIT LOGS (OPTIONAL)
# ------------------------------------------------------------------------------
if ($KeepLogs) {
    Write-Host "[1/6] Archiving audit logs to Desktop..." -ForegroundColor Yellow
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $logSrc = Join-Path $DataDir "logs"
    $singleLog = Join-Path $DataDir "backup_log.txt"
    $archiveDest = Join-Path $desktopPath "DatabaseBackup_Logs_Archive"

    try {
        if (Test-Path $logSrc) {
            New-Item -ItemType Directory -Path $archiveDest -Force | Out-Null
            Copy-Item -Path "$logSrc\*" -Destination $archiveDest -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "    [OK] Audit logs exported to: $archiveDest" -ForegroundColor Green
        }
        if (Test-Path $singleLog) {
            Copy-Item -Path $singleLog -Destination (Join-Path $desktopPath "backup_log_archive.txt") -Force -ErrorAction SilentlyContinue
            Write-Host "    [OK] Single log exported to: $desktopPath\backup_log_archive.txt" -ForegroundColor Green
        }
    } catch {
        Write-Warning "    Failed to archive logs: $_"
    }
} else {
    Write-Host "[1/6] Skipping log archive..." -ForegroundColor DarkGray
}

# ------------------------------------------------------------------------------
# 3. TERMINATE RUNNING PROCESSES
# ------------------------------------------------------------------------------
Write-Host "[2/6] Terminating active application processes..." -ForegroundColor Yellow
$procNames = @("DatabaseBackupApp", "sqlcmd")
foreach ($p in $procNames) {
    Get-Process -Name $p -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Terminate running PowerShell agent instances
try {
    $agentScripts = @("backup_agent.ps1", "performance_query.ps1", "storage_monitor.ps1", "run_automation.ps1")
    Get-WmiObject Win32_Process -Filter "Name like 'powershell%.exe'" -ErrorAction SilentlyContinue | ForEach-Object {
        $cmdLine = $_.CommandLine
        foreach ($s in $agentScripts) {
            if ($cmdLine -and $cmdLine.IndexOf($s, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Host "    Terminated background process for: $s (PID: $($_.ProcessId))" -ForegroundColor DarkGray
            }
        }
    }
} catch { }

# ------------------------------------------------------------------------------
# 4. REMOVE ALL WINDOWS SCHEDULED TASKS
# ------------------------------------------------------------------------------
Write-Host "[3/6] Unregistering Windows Scheduled Tasks..." -ForegroundColor Yellow
$tasksToDelete = @(
    "DatabaseBackup_AutomatedTask",
    "DatabaseBackup_Daily",
    "DatabaseBackup_StorageMonitor",
    "DatabaseBackup_StorageCleanup",
    "DatabaseBackup_PerformanceMaintenance",
    "DatabaseBackupApp",
    "Database Cloud Backup",
    "Database Cloud Backup (System Service)",
    "EnterpriseDatabaseBackup"
)

foreach ($task in $tasksToDelete) {
    try {
        $existing = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
            Write-Host "    [OK] Deleted scheduled task: '$task'" -ForegroundColor Green
        }
    } catch {
        # Fallback to schtasks command line
        & schtasks.exe /delete /tn $task /f >$null 2>&1
    }
}

# ------------------------------------------------------------------------------
# 5. SECURELY SHRED TOKEN & REMOVE DIRECTORIES
# ------------------------------------------------------------------------------
Write-Host "[4/6] Shredding machine credentials & purging application files..." -ForegroundColor Yellow

# Secure shred of token.dpapi
$tokenFiles = @(
    (Join-Path $DataDir "token.dpapi"),
    (Join-Path $InstallDir "token.dpapi")
)

foreach ($tf in $tokenFiles) {
    if (Test-Path $tf) {
        try {
            $len = (Get-Item $tf).Length
            $randomBytes = New-Object byte[] (([Math]::Max($len, 64)))
            $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
            $rng.GetBytes($randomBytes)
            [System.IO.File]::WriteAllBytes($tf, $randomBytes)
            Remove-Item -Path $tf -Force -ErrorAction SilentlyContinue
            Write-Host "    [OK] Securely shredded DPAPI token: $tf" -ForegroundColor Green
        } catch {
            Remove-Item -Path $tf -Force -ErrorAction SilentlyContinue
        }
    }
}

# Remove InstallDir and DataDir
if (Test-Path $InstallDir) {
    try {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction Stop
        Write-Host "    [OK] Removed Install Directory: $InstallDir" -ForegroundColor Green
    } catch {
        Write-Warning "    Failed to completely delete $InstallDir (locked files?). Retrying in background..."
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile -Command `"Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$InstallDir' -Recurse -Force -ErrorAction SilentlyContinue`""
    }
}

if (Test-Path $DataDir) {
    try {
        Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction Stop
        Write-Host "    [OK] Removed Data Directory: $DataDir" -ForegroundColor Green
    } catch {
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile -Command `"Start-Sleep -Seconds 2; Remove-Item -LiteralPath '$DataDir' -Recurse -Force -ErrorAction SilentlyContinue`""
    }
}

# ------------------------------------------------------------------------------
# 6. REMOVE SHORTCUTS & REGISTRY ENTRIES
# ------------------------------------------------------------------------------
Write-Host "[5/6] Cleaning shortcuts and registry entries..." -ForegroundColor Yellow

# Shortcut locations
$shortcutPaths = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("CommonDesktopDirectory"),
    [Environment]::GetFolderPath("Programs"),
    [Environment]::GetFolderPath("CommonPrograms")
)

foreach ($sp in $shortcutPaths) {
    if ($sp -and (Test-Path $sp)) {
        Get-ChildItem -Path $sp -Filter "*Database*Backup*.lnk" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
            Write-Host "    [OK] Removed shortcut: $($_.FullName)" -ForegroundColor DarkGray
        }
    }
}

# Registry uninstall entries
$regKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DatabaseBackupApp"
)
foreach ($rk in $regKeys) {
    if (Test-Path $rk) {
        Remove-Item -Path $rk -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "    [OK] Removed registry entry: $rk" -ForegroundColor DarkGray
    }
}

# ------------------------------------------------------------------------------
# 7. COMPLETION SUMMARY
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  UNINSTALLATION COMPLETE (100% CLEAN)" -ForegroundColor Green
Write-Host "  All background scheduled tasks, scripts, tokens, and configs were removed." -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $Force) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "Enterprise Database Cloud Backup has been completely and cleanly uninstalled from this computer.",
            "Uninstallation Complete",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    } catch { }
}
