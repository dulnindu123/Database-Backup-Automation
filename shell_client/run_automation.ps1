<#
.SYNOPSIS
    Enterprise Database Cloud Backup Automation - Master Orchestrator (v4.3.0)
.DESCRIPTION
    Unified executor matching the 3-module workflow:
    1. DB Backup (Backup, Compress, Encrypt, Upload to Customer Drive Folder & log to [DB Backups])
    2. Server Cleanup Scan (Fixed drive evaluation, purge temporary files & log to [Server Cleanup])
    3. Performance Query (SQL DMV latency benchmarks & log to [Performance Query])
    
    All executions stream overall Run Details to Master "Application report" -> [Customer Tab].
#>

[CmdletBinding()]
param(
    [ValidateSet("All", "Backup", "Cleanup", "Performance")]
    [string]$Task = "All",

    [ValidateSet("Automatic", "Manual")]
    [string]$Mode = "Manual",

    [string]$ConfigDir = "C:\ProgramData\DatabaseBackupApp",
    [string]$InstallDir = "C:\Program Files\DatabaseBackupApp"
)

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { $InstallDir }
$backupScript  = Join-Path $scriptDir "backup_agent.ps1"
$cleanupScript = Join-Path $scriptDir "storage_monitor.ps1"
$perfScript    = Join-Path $scriptDir "performance_query.ps1"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "DATABASE BACKUP & AUTOMATION WORKFLOW ORCHESTRATOR" -ForegroundColor Cyan
Write-Host "Mode: $Mode | Task: $Task | Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. DB Backup
if ($Task -eq "All" -or $Task -eq "Backup") {
    Write-Host "`n>>> [MODULE 1/3] EXECUTING DATABASE BACKUP..." -ForegroundColor Blue
    if (Test-Path $backupScript) {
        & $backupScript -ConfigDir $ConfigDir -InstallDir $InstallDir -RunMode $Mode
    } else {
        Write-Warning "Backup script missing: $backupScript"
    }
}

# 2. Server Cleanup Scan
if ($Task -eq "All" -or $Task -eq "Cleanup") {
    Write-Host "`n>>> [MODULE 2/3] EXECUTING SERVER CLEANUP SCAN..." -ForegroundColor Green
    if (Test-Path $cleanupScript) {
        & $cleanupScript -ConfigDir $ConfigDir -RunMode $Mode
    } else {
        Write-Warning "Storage cleanup script missing: $cleanupScript"
    }
}

# 3. Performance Query
if ($Task -eq "All" -or $Task -eq "Performance") {
    Write-Host "`n>>> [MODULE 3/3] EXECUTING DATABASE PERFORMANCE QUERY..." -ForegroundColor Magenta
    if (Test-Path $perfScript) {
        & $perfScript -ConfigDir $ConfigDir -RunMode $Mode
    } else {
        Write-Warning "Performance query script missing: $perfScript"
    }
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "AUTOMATION CYCLE COMPLETED ACROSS ALL MODULES" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
