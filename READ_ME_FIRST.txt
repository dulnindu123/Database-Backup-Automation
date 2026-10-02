================================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & AUDIT LOG SYSTEM (Zero-Trust v4.1.0)
  Client Installation, Deployment & Operations Quick Reference
================================================================================

Welcome to the Enterprise Database Cloud Backup system (v4.1.0 Multi-Module Edition).
This package delivers an air-gapped, zero-trust disaster recovery solution that
encrypts Microsoft SQL Server database backups with AES-256-GCM + RSA-4096 (DBK2 format),
transfers them via a Cloud Run Upload Broker to retention-locked GCS cloud storage,
and logs multi-module telemetry (Backup Automation, Server Cleanup) to a dedicated
Customer Master Google Sheet and Customer Google Drive folder.

--------------------------------------------------------------------------------
ZERO-TRUST SECURITY ARCHITECTURE:
--------------------------------------------------------------------------------
- ZERO Google Credentials on Client PCs: Customer machines hold no GCP service
  account keys or OAuth secrets. A compromised client cannot read, list, or delete
  any backup files stored in the cloud.
- Dedicated Per-Customer Cloud Run Broker: Each customer is provisioned with an
  isolated Cloud Run broker instance (`broker-<slug>`) and IAM-conditioned bucket
  prefix (`<slug>/`).
- Ed25519 Signed Manifest & Zero-Typing Installation: Installation packages are
  sealed with an administrator Ed25519 digital signature. The installer verifies
  authenticity before setup, automatically locks the broker URL, and seals the
  machine token directly into Windows DPAPI storage. The customer types nothing!
- Tamper Resistance: Any tampering with the package, URLs, or manifest triggers
  immediate rejection (`ERR_MANIFEST_TAMPERED`) and halts installation.
- Air-Gapped Keypairs: Backups are encrypted locally using public keys (`backup_public.pem`
  and `escrow_public.pem`). Private decryption keys remain strictly offline on admin hardware.
- Retention Protection: Backups are stored in GCS with retention policy
  (permanently locked into WORM mode against administrative deletion).
- Single Unified Persistent Log: All modules log to a single consolidated log file
  at `C:\ProgramData\DatabaseBackupApp\backup_log.txt` with zero fragmented log files.

--------------------------------------------------------------------------------
QUICK START (ZERO-TYPING INSTALLATION):
--------------------------------------------------------------------------------
METHOD 1: Graphical Setup Wizard ("Setup_DatabaseBackup.exe") - Recommended
  - Right-click "Setup_DatabaseBackup.exe" and choose "Run as Administrator".
  - The installer verifies the Ed25519 signed manifest automatically.
  - When verified, the green badge confirms zero typing is needed:
    "AUTHENTIC ED25519 SIGNED PACKAGE (<CUSTOMER_SLUG>) - ZERO TYPING REQUIRED".
  - Your dedicated Cloud Run Broker URL and authentication token are pre-loaded
    and locked against accidental modification.
  - Click "Install Now". The token is sealed into Windows DPAPI storage,
    shortcuts are created, and the unattended schedule is registered automatically.

METHOD 2: Automated Silent Batch Installer ("1_Quick_Install.bat")
  - Right-click "1_Quick_Install.bat" and run as Administrator.
  - The script copies application files, seals the DPAPI machine token,
    applies secure folder ACLs, and registers scheduled tasks with 0 user prompts.

METHOD 3: In-Place Update ("Update_App.bat")
  - Automatically preserves existing `token.dpapi`, `backup_public.pem`,
    `escrow_public.pem`, `backup_log.txt`, and `config.json`.
  - Updates all program binaries and applies secure ACLs.

--------------------------------------------------------------------------------
POST-INSTALL CONFIGURATION (IN APPLICATION):
--------------------------------------------------------------------------------
1. Launch "Database Cloud Backup" from your Desktop.
2. In the "Settings" tab:
   - Your dedicated Upload Broker URL is pre-configured and locked (🔒 Locked).
   - Machine token status displays active (🔑 Token: Active).
   - Enter your Customer Google Drive Folder ID or Link (click "Open Folder ->" to test).
   - Enter your Customer Master Google Sheet ID or Link (click "Open Sheet ->" to test).
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
  SYSTEM_ARCHITECTURE_AND_CODE_GUIDE.md -> Exhaustive codebase guide and system architecture
  docs_assets/                       -> High-resolution UI screenshots & workflow walkthrough
  images/                            -> Visual walkthrough assets
  Tools/                             -> Admin key generation and offline recovery utilities
  AppFiles/                          -> Compiled standalone application binaries & public keys

================================================================================
