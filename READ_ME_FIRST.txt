================================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & AUDIT LOG SYSTEM (Zero-Trust v4.1.0)
  Client Installation, Deployment & Operations Quick Reference
================================================================================

Welcome to the Enterprise Database Cloud Backup system (v4.1.0 Multi-Module Edition).
This package delivers an air-gapped, zero-trust disaster recovery solution that
encrypts Microsoft SQL Server database backups with AES-256-GCM + RSA-4096 (DBK2 format),
transfers them via a Cloud Run Upload Broker to retention-locked GCS cloud storage,
and logs multi-module telemetry (Backup, Server Cleanup, Performance Query) to a dedicated
Customer Master Google Sheet and Customer Google Drive folder.

--------------------------------------------------------------------------------
ZERO-TRUST SECURITY ARCHITECTURE:
--------------------------------------------------------------------------------
- ZERO Google Credentials on Client PCs: Customer machines hold no GCP service
  account keys or OAuth secrets. A compromised client cannot read, list, or delete
  any backup files stored in the cloud.
- DPAPI Machine Token Authentication: Client PCs authenticate strictly via a Windows
  DPAPI-encrypted machine token (`token.dpapi`), bound natively to the local machine.
- Air-Gapped Keypairs: Backups are encrypted locally using public keys (`backup_public.pem`
  and `escrow_public.pem`). Private decryption keys remain strictly offline on admin hardware.
- Retention Protection: Backups are stored in GCS with retention policy
  (permanently locked into WORM mode against administrative deletion).
- Single Unified Persistent Log: All modules log to a single consolidated log file
  at `C:\ProgramData\DatabaseBackupApp\backup_log.txt` with zero fragmented log files.

--------------------------------------------------------------------------------
QUICK START (HOW TO INSTALL):
--------------------------------------------------------------------------------
METHOD 1: Graphical Setup Wizard ("Setup_DatabaseBackup.exe") - Recommended
  - Right-click "Setup_DatabaseBackup.exe" and choose "Run as Administrator".
  - Review destination folder and verify or enter your Cloud Run Broker URL.
  - Click "⚡ Auto-Fetch & Test" to verify live endpoint reachability.
  - If a "raw_token.txt" was provided, it is automatically encrypted into "token.dpapi".
  - Click "Install Now". Shortcuts and automatic schedule will be configured.

METHOD 2: Automated Silent Batch Installer ("1_Quick_Install.bat")
  - If deploying a new PC, place `raw_token.txt` (from admin) in this folder.
  - Right-click "1_Quick_Install.bat" and run as Administrator.
  - The script copies application files, encrypts `raw_token.txt` via local DPAPI,
    wipes the plaintext transfer file, applies folder ACLs, and registers shortcuts.

METHOD 3: In-Place Update ("Update_App.bat")
  - Automatically preserves existing `token.dpapi`, `backup_public.pem`,
    `escrow_public.pem`, `backup_log.txt`, and `config.json`.
  - Encrypts `raw_token.txt` if updating token.
  - Updates all program binaries and applies secure ACLs.

--------------------------------------------------------------------------------
POST-INSTALL CONFIGURATION (IN APPLICATION):
--------------------------------------------------------------------------------
1. Launch "Database Cloud Backup" from your Desktop.
2. In the "Settings" tab:
   - Enter your Customer Google Drive Folder ID or Link (click "Open Folder ->" to test).
   - Enter your Customer Master Google Sheet ID or Link (click "Open Sheet ->" to test).
   - If Token badge shows MISSING, click "[🔑 Import Token]" to paste your token string
     or select your "raw_token.txt" file.
   - Click "[🔍 Test Broker Connection]" to verify zero-trust authentication.
   - Click "[💾 Save Settings]".

--------------------------------------------------------------------------------
PACKAGE CONTENTS:
--------------------------------------------------------------------------------
  Setup_DatabaseBackup.exe           -> Graphical setup wizard with live broker testing
  1_Quick_Install.bat                -> One-click automated silent installation script
  Update_App.bat                     -> Safe in-place updater (preserves existing configs)
  Uninstall.bat                      -> Clean uninstaller (removes tasks, shortcuts, registry)
  READ_ME_FIRST.txt                  -> This quick-start guide
  USER_GUIDE.md                      -> Complete technical engineering and architectural runbook
  Enterprise_Database_Cloud_Backup_Master_Guide.docx -> Enterprise Word format deployment manual
  SYSTEM_ARCHITECTURE_AND_CODE_GUIDE.md -> Exhaustive codebase guide and system architecture
  docs_assets/                       -> High-resolution UI screenshots & workflow walkthrough
  images/                            -> Visual walkthrough assets
  Tools/                             -> Admin key generation and offline recovery utilities
  AppFiles/                          -> Compiled standalone application binaries & public keys

================================================================================
