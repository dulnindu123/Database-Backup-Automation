================================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & MAINTENANCE SUITE (v5.0.0)
  Customer Field Installation & Quick Setup Guide
================================================================================

Welcome to Enterprise Database Cloud Backup (v5.0.0).
This package provides automated, Zero-Trust database backups to cloud storage,
automated index maintenance, and multi-module server telemetry.

--------------------------------------------------------------------------------
1. FAST INSTALLATION (CHOOSE OPTION A OR OPTION B)
--------------------------------------------------------------------------------

OPTION A: GRAPHICAL SETUP WIZARD (RECOMMENDED FOR WINDOWS SERVERS & PCS)
   * Supported: Windows Server 2016-2025, Windows 10/11, Windows Server 2012 R2.
   1. Right-click Setup_DatabaseBackup.exe -> Run as administrator.
   2. The installer automatically validates the Ed25519 digital signature.
   3. Check/uncheck shortcut and schedule options, then click "Install Now".
   4. The installer configures:
      - Program Files binaries (C:\Program Files\DatabaseBackupApp)
      - Machine-scoped DPAPI authentication vault (token.dpapi)
      - Windows Task Scheduler unattended backup service (NT AUTHORITY\SYSTEM)
      - Desktop and Start Menu shortcuts
   5. Launch the application, select target databases, and click "Run Cloud Backup Now".

OPTION B: POWERSHELL LIGHTWEIGHT AGENT (FOR LEGACY OS & HEADLESS SERVERS)
   * Supported: Windows Server 2008 R2, 2012, 2012 R2, Windows 7, 8.1, 32-bit x86.
   * Zero Python dependency, zero .EXE binaries, under 30 KB disk footprint.
   1. Open an elevated PowerShell prompt (Run as Administrator).
   2. Navigate into the shell_client folder:
      cd shell_client
   3. Run the unattended installer:
      powershell.exe -ExecutionPolicy Bypass -File .\install_agent.ps1
   4. The agent enforces TLS 1.2 and registers automated scheduled tasks immediately.
   5. Run a test backup:
      powershell.exe -ExecutionPolicy Bypass -File "C:\Program Files\DatabaseBackupApp\backup_agent.ps1"

--------------------------------------------------------------------------------
2. EXTERNAL SQL CREDENTIALS (SQLPara.txt)
--------------------------------------------------------------------------------
For security-hardened environments where plaintext database passwords must NOT
be stored in config.json:

1. Copy "SQLPara.txt.template" to "SQLPara.txt" (or place in C:\SPIL\SQLPara).
2. Enter your SQL Server credentials in either standard format:
   server=localhost\SQLEXPRESS
   user=sa
   password=YourStrongPasswordHere
   database=YourDatabaseName
3. The backup engine automatically prioritizes SQLPara.txt over config.json.

--------------------------------------------------------------------------------
3. ZERO-TRUST ENCRYPTION & DATA RESTORATION
--------------------------------------------------------------------------------
- Encrypted Backups (.dbk2):
  Backups are encrypted locally with per-chunk AES-256-GCM. The encryption key is
  sealed using dual 4096-bit RSA public keys (Customer Key + Escrow Key).
  Private keys stay offline on the air-gapped Administrator machine.

- Standard Unencrypted Backups (.zip):
  If the Zero-Trust encryption checkbox is unticked, backups are saved as
  standard compressed .zip archives. When unticked, automated security alerts
  are dispatched to IT administrators.

- Restoring a Database:
  Open DatabaseBackupApp -> Go to "Database Restore" tab -> Browse your .dbk2 or
  .zip file -> Provide private recovery key (.pem) if encrypted -> Click Restore.

--------------------------------------------------------------------------------
4. UPGRADING & UNINSTALLING
--------------------------------------------------------------------------------
- To Update an Existing Installation: Run "Update_App.bat" as Administrator.
  Settings, tokens, and customer encryption keys are preserved automatically.
- To Uninstall: Run "Uninstall.bat" as Administrator.

--------------------------------------------------------------------------------
DOCUMENTATION:
For detailed technical documentation, see: INSTALLATION_GUIDE_v5.0.md
================================================================================

