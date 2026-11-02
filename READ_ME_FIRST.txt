================================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & MAINTENANCE SUITE (v4.2.0)
  Client / Customer Quick Start & Field Configuration Guide
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
CONFIGURATION FIELDS REFERENCE: WHAT TO FILL & WHERE TO FIND THEM
--------------------------------------------------------------------------------
During setup (or when reviewing C:\ProgramData\DatabaseBackupApp\config.json),
you will encounter the following configuration fields:

1. SQL SERVER INSTANCE / HOST (SQL_SERVER_INSTANCE)
   • What to Fill:
     The network address or instance name of your Microsoft SQL Server.
     - Default instance on same machine : localhost  (or . or 127.0.0.1)
     - Named instance (e.g. Express)    : .\SQLEXPRESS  (or localhost\SQLEXPRESS)
     - Remote / Network SQL Server      : SERVERNAME\INSTANCE  (or 192.168.1.10)
   • Where to Get It:
     - Method A (SSMS): Open SQL Server Management Studio. Look at the login
       box labeled "Server name:". Copy that exact text.
     - Method B (Services): Press Win+R -> type "services.msc" -> press Enter.
       Find "SQL Server (...)". If it says "SQL Server (MSSQLSERVER)", use
       "localhost". If it says "SQL Server (SQLEXPRESS)", use ".\SQLEXPRESS".
     - Method C (CMD): Run "hostname" in Command Prompt.

2. TARGET DATABASE(S) (DATABASE_NAME / TARGET_DATABASES)
   • What to Fill:
     The exact name(s) of the SQL Server database(s) to back up.
     If backing up multiple databases, separate with commas:
     e.g., TheDatabase, GlassSheet, ERP_PROD
   • Where to Get It:
     - Open SSMS -> connect to your server -> expand the "Databases" tree.
     - Or query SQL: SELECT name FROM sys.databases WHERE database_id > 4;
     - Or check with your software vendor / ERP administrator.

3. SQL AUTHENTICATION CREDENTIALS (SQL_USERNAME & SQL_PASSWORD)
   • What to Fill:
     - Windows Authentication (Recommended): Leave Username & Password BLANK.
       The service will use the Windows system account.
     - SQL Server Authentication: Enter the SQL Login name (e.g. "sa" or
       "backup_svc") and the corresponding password.
   • Where to Get It:
     - Provided by your internal Database Administrator (DBA).
     - Permissions required: db_backupoperator & db_datareader (or sysadmin).

4. LOCAL BACKUP DESTINATION FOLDER (BACKUP_FOLDER)
   • What to Fill:
     Full path to a dedicated local directory for staging compressed archives.
     e.g., C:\SQLBackups  or  D:\DatabaseBackups
   • Where to Get It:
     - Open Windows File Explorer -> select a local physical drive with at least
       2x the uncompressed database size available -> create a dedicated folder.
   • CRITICAL SECURITY RULE:
     - NEVER use OneDrive (C:\Users\...\OneDrive\Backups), Dropbox, or Google
       Drive folders. The software automatically blocks cloud-synced folders
       to prevent infinite sync loops and file locking errors.

5. CLOUD BROKER URL (BROKER_URL)
   • What to Fill:
     The secure HTTPS Google Apps Script gateway endpoint.
     e.g., https://script.google.com/macros/s/AKfycb.../exec
   • Where to Get It:
     - Already pre-configured inside your signed "bundle.json".
     - Or provided by your Cloud Backup Administrator.

6. CUSTOMER SLUG & ENROLLMENT CODE (CUSTOMER_SLUG & ENROLL_CODE)
   • What to Fill:
     - Customer Slug: Your company's unique lowercase ID (e.g., "acme", "fmi").
     - Enrollment Code: One-time token used to bind this machine (e.g. "ACME@...").
   • Where to Get It:
     - Automatically imported from the included "bundle.json".
     - Or provided in your Onboarding Credentials sheet.

7. AUTOMATED BACKUP SCHEDULE (SCHEDULE_DAYS & SCHEDULE_TIME)
   • What to Fill:
     - Days: e.g. MON  or  MON,WED,FRI  or  MON,TUE,WED,THU,FRI,SAT,SUN
     - Time: 24-hour format HH:MM (e.g., 02:00 for 2:00 AM, 23:30 for 11:30 PM).
   • Where to Get It:
     - Agree with your team on a nightly maintenance window when users are
       logged off and database activity is lowest.

8. LOCAL RETENTION & CLEANUP (RETENTION_DAYS & CLEANUP_THRESHOLD_PERCENT)
   • What to Fill:
     - Retention Days (default: 30): How many days local backups remain before
       the server cleanup engine automatically deletes them.
     - Threshold % (default: 85): If disk space exceeds 85% used, emergency
       purge cleans old staging dumps immediately.
   • Where to Get It:
     - Standard values (30 days / 85%) are pre-set and recommended.

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
- Full installation guide: CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx
- Cloud Architecture: Google_Sheets_Architecture_and_Structure_Guide.docx
================================================================================
