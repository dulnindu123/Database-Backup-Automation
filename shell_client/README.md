# 🐚 Native Windows PowerShell Shell Client
### Zero-Footprint, 100% Native Windows Script Agent · v4.2.0

This directory provides a **100% native Windows PowerShell shell agent** for the **Enterprise Database Cloud Backup Automation System**.

---

## 🎯 Why Use the PowerShell Shell Agent?

* **Zero Footprint**: Requires **no Python**, **no compiled executables**, and **no package managers**. Total size is under **30 KB**.
* **Enterprise Server Compliant**: Ideal for headless Windows Server environments, Active Directory GPO deployments, and locked-down database servers where running unapproved `.exe` files is restricted by security policies.
* **Full Zero-Trust Parity**:
  * Authenticates via machine tokens sealed into **Windows DPAPI** (`token.dpapi`).
  * Backs up databases natively via `sqlcmd`, `mysqldump`, or `pg_dump`.
  * Encrypts dumps using **AES-256 + dual RSA-4096 envelope encryption**.
  * Communicates with the same serverless **Google Apps Script Web App Broker** (`Code.gs`).
  * Logs all telemetry directly to the **Master Google Sheet**.

---

## 📁 Files Included

| File | Purpose |
|---|---|
| **`install_agent.ps1`** | Elevated setup script: computes hardware fingerprint, auto-enrolls with broker, seals machine token in DPAPI, registers Windows Scheduled Tasks. |
| **`backup_agent.ps1`** | Autonomous backup executor: dumps database, compresses to `.zip`, encrypts into `.dbk2`, streams chunked PUT to Google Drive, reports status to Google Sheet. |
| **`storage_monitor.ps1`** | Hourly storage health scanner: monitors fixed drives and reports disk pressure to Google Sheet. |

> 🔒 **Decryption Security Note**: Client machines hold **only public keys** and cannot decrypt backups. Decryption is performed strictly by authorized administrators on an air-gapped machine using **`admin_recovery_tool/`**.

---

## 🚀 Quick Start (Deployment on Windows Server)

### Step 1: Run the Elevated Installer
Open an elevated **PowerShell** prompt (Run as Administrator) in this folder:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\install_agent.ps1
```

If you have a customer `bundle.json` in the same directory, the installer will automatically read all parameters without any typing!

Alternatively, pass parameters directly:
```powershell
powershell.exe -ExecutionPolicy Bypass -File .\install_agent.ps1 `
    -BrokerUrl "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec" `
    -CustomerSlug "acme" `
    -EnrollCode "YOUR_SECRET_ENROLL_CODE" `
    -BackupFolder "C:\SQLBackups"
```

The script will:
1. Compute the machine hardware fingerprint.
2. Enroll the server with your Google Apps Script broker.
3. Seal the received machine token in `C:\ProgramData\DatabaseBackupApp\token.dpapi`.
4. Register the daily automated task: **`DatabaseBackup_AutomatedTask`**.
5. Register the hourly storage monitor: **`DatabaseBackup_StorageMonitor`**.

---

### Step 2: Run a Manual Test Backup
To trigger an immediate backup from the console:

```powershell
powershell.exe -ExecutionPolicy Bypass -File "C:\Program Files\DatabaseBackupApp\backup_agent.ps1"
```

You will see real-time progress:
```text
[SYSTEM] STARTING AUTOMATED DATABASE BACKUP EXECUTION CYCLE
[AUTH] DPAPI Token decrypted successfully. Machine ID: pc-acme-a1b2c3d4
[BROKER] Broker verified active machine: pc-acme-a1b2c3d4
[BACKUP] Executing database dump for: ProductionDB (MSSQL)...
[COMPRESS] Compressing dump archive into .zip...
[CRYPTO] Encrypting archive into zero-trust .dbk2 container...
[UPLOAD] Requesting Google Drive upload session from Upload Broker...
[UPLOAD] Streaming encrypted chunks directly to Google Drive...
[TELEMETRY] Telemetry logged successfully to Audit/Telemetry sheet tabs.
[SYSTEM] BACKUP CYCLE COMPLETED SUCCESSFULLY
```

---

## 🔍 Log Files & Verification

* **Persistent Log**: `C:\ProgramData\DatabaseBackupApp\backup_log.txt`
* **Configuration**: `C:\ProgramData\DatabaseBackupApp\config.json`
* **DPAPI Machine Vault**: `C:\ProgramData\DatabaseBackupApp\token.dpapi`
* **Scheduled Tasks**: Check in `taskschd.msc` under `Task Scheduler Library`.
