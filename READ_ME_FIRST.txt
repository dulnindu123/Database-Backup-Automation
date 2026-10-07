================================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & MAINTENANCE SUITE (v4.2.0)
  Client / Customer Quick Start Guide
================================================================================

Welcome to the Enterprise Database Cloud Backup & Maintenance Suite.
This package contains everything needed to install the automated backup agent,
storage monitor, and database performance maintenance tasks on this server.

--------------------------------------------------------------------------------
QUICK INSTALLATION (TWO EASY OPTIONS):
--------------------------------------------------------------------------------

OPTION 1: NATIVE WINDOWS POWERSHELL AGENT (RECOMMENDED FOR SERVERS)
   Zero external dependencies. Zero Python installation required.
   
   1. Open an elevated PowerShell prompt (Right-click -> Run as Administrator).
   2. Navigate to the shell_client folder:
      cd shell_client
   3. Run the installer script:
      powershell.exe -ExecutionPolicy Bypass -File .\install_agent.ps1
   4. The agent will configure local directories and register the scheduled tasks:
      - DatabaseBackup_Daily
      - DatabaseBackup_StorageCleanup
      - DatabaseBackup_PerformanceMaintenance

OPTION 2: GRAPHICAL SETUP WIZARD (DESKTOP APPLICATION)
   1. Right-click Setup_DatabaseBackup.exe -> Run as administrator.
   2. Follow the on-screen installation prompts.
   3. The installer will set up the program files, register background services,
      and add a desktop shortcut.

--------------------------------------------------------------------------------
MAINTENANCE MODULES INCLUDED:
--------------------------------------------------------------------------------
- MODULE 1: Database Backup Engine (backup_agent.ps1)
  Performs compressed, AES-256-GCM + RSA-4096 dual-envelope encrypted backups
  and uploads directly to your dedicated cloud folder.
  
- MODULE 2: Server Cleanup Scan (storage_monitor.ps1)
  Monitors server disk space, cleans expired local staging archives, and rotates logs.
  
- MODULE 3: Database Performance Maintenance (performance_query.ps1)
  Inspects table index fragmentation, executes a safety pre-backup, performs
  database consistency check (DBCC CHECKDB), rebuilds indexes (DBCC DBREINDEX 80),
  updates optimizer statistics (sp_updatestats), and reports metrics to cloud telemetry.

--------------------------------------------------------------------------------
SECURITY ASSURANCE:
--------------------------------------------------------------------------------
- All database backups are encrypted client-side using public keys.
- Even if this server were compromised, the encrypted backups cannot be decrypted
  without the administrator's offline private keys.
--------------------------------------------------------------------------------
HOW TO UNINSTALL:
--------------------------------------------------------------------------------
- Via GUI / Windows: Open Windows Settings -> Apps -> Installed apps -> Uninstall,
  or double-click Uninstall.bat in this package / application directory.
- Via PowerShell Agent: Open elevated PowerShell and run:
  powershell.exe -ExecutionPolicy Bypass -File .\shell_client\uninstall_agent.ps1

--------------------------------------------------------------------------------
DOCUMENTATION & SUPPORT:
--------------------------------------------------------------------------------
- Full installation guide: CLIENT_INSTALLATION_GUIDE.md
- Technical details: README.md
- Shell client guide: shell_client\README.md
================================================================================
