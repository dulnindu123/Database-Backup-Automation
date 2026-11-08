# 🛠️ Enterprise Database Cloud Backup Automation · System Setup & Deployment Guide
### Zero-Trust Multi-Tenant Cloud Architecture · Version 5.0.0

**Classification:** Internal Engineering & Administrator Setup Runbook  
**App Version:** `v5.0.0` (November 2026 Post-Audit Hardened Release)  
**Security Standard:** Zero-Trust Client Cryptography (AES-256-GCM + Dual RSA-4096)  

---

## 📌 Architecture Overview

The system operates across three strictly segregated tiers:
1. **Central Administrator Workstation (Air-Gapped / Trusted)**: Houses administrative Ed25519 signing keys, customer provisioning scripts (`batch_setup_customers.py`), and offline RSA-4096 private keys (`backup_private.pem`, `escrow_private_{slug}.pem`).
2. **Google Cloud Infrastructure (Zero-Trust Broker & Storage)**: Google Apps Script Web App (`Code.gs`) running under administrative credentials, Google Drive customer folders, and Google Sheets centralized telemetry.
3. **Customer Database Servers (Untrusted / Exposed)**: Hold public keys only. Dumps are compressed, encrypted locally, and streamed directly to Google Drive via presigned resumable upload sessions.

---

## 🚀 Step 1: Deploy Central Google Cloud Infrastructure

### 1.1 Create Master Google Drive Resources
1. In your administrative Google Workspace account, create a master root folder:
   **`Enterprise Customer Backups`**
2. Copy the Folder ID from the browser URL:
   `https://drive.google.com/drive/folders/`**`1FOLDER_ID_HERE`**
3. Create customer subfolders (or let `Code.gs` auto-create them dynamically upon customer enrollment).

### 1.2 Create Master Google Sheets Telemetry Database
1. Create a Google Sheet named **`Application report`**.
2. Copy the Spreadsheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/`**`1SHEET_ID_HERE`**`/edit`
3. This spreadsheet will hold the master `Tokens` registry, `Config` tab, and dedicated reporting tabs for all 70+ customers.

### 1.3 Deploy Google Apps Script Broker (`Code.gs`)
1. Open [script.google.com](https://script.google.com) and create a New Project.
2. Replace default code with `BackupAutomation_v5.0/apps_script_broker/Code.gs`.
3. Configure the resource IDs at the top of `Code.gs`:
   ```javascript
   const MASTER_APPLICATION_REPORT_SPREADSHEET_ID = "YOUR_SPREADSHEET_ID";
   const PARENT_BACKUP_FOLDER_ID = "YOUR_FOLDER_ID";
   const ADMIN_ALERT_EMAIL = "dulnindu@spillabs.com";
   ```
4. Click **Deploy** -> **New Deployment** -> select **Web App**.
   - **Execute as:** `Me` (administrator account).
   - **Who has access:** `Anyone` (authentication handled cryptographically via SHA-256 machine token hashes in `Code.gs`).
5. Copy the generated Web App URL (`https://script.google.com/macros/s/.../exec`).
6. Set up the hourly Missed-Backup Sentinel trigger:
   - In Apps Script, click **Triggers** (alarm icon on left sidebar).
   - Click **Add Trigger** -> Choose `checkMissedBackups` -> Event source: `Time-driven` -> `Hour timer` -> `Every hour`.

---

## 🔐 Step 2: Setup Admin Workstation & Keys

### 2.1 Prepare Administrative Virtual Environment
On your central IT workstation:
```cmd
cd Admin_Installation_Package
Setup_Admin_Environment.bat
```

### 2.2 Generate Administrative Keys
1. **Admin Ed25519 Signing Key**:
   Used to digitally sign `bundle.json` manifests for zero-typing customer enrollment.
   ```cmd
   python 1_Customer_Provisioning/generate_keys.py --type ed25519
   ```
2. **Customer RSA-4096 Keypairs**:
   Each customer receives an isolated Primary keypair and a Tenant-Isolated Escrow keypair (`escrow_public_{slug}.pem` / `escrow_private_{slug}.pem`).
3. **Air-Gap Private Keys (Audit Finding F-05)**:
   Ensure all `*_private.pem` files and passphrases reside on encrypted offline media (BitLocker USB drive) outside OneDrive-synced folder trees.

---

## 👥 Step 3: Provision Customer Installation Packages

### 3.1 Single Customer Provisioning:
```cmd
python 1_Customer_Provisioning/setup_new_customer.py
```
Follow prompts to enter customer slug (e.g., `blisscoglass`), broker URL, and passphrases.

### 3.2 Batch Provisioning (70+ Customers):
```cmd
python 1_Customer_Provisioning/batch_setup_customers.py
```
Reads `customer_slugs.txt` and automatically generates deployment packages in `Distributable_Packages/<slug>_Installation_Package/`.

---

## 💻 Step 4: Client Deployment Pathways

| Environment | Recommended Deployment | Execution Command |
| :--- | :--- | :--- |
| **Modern Windows Server (GUI)** | Graphical Setup Wizard | Run `Setup_DatabaseBackup.exe` as Administrator |
| **Server Core / PowerShell** | Pure PowerShell Shell Agent | `cd shell_client && powershell -ExecutionPolicy Bypass -File .\install_agent.ps1` |
| **DevOps / CI Batch** | Command-Line Interface | `DatabaseBackupCLI.exe --backup --verify` |

---

## 🧪 Step 5: Verification & Audit Testing

Run the automated security audit suite to verify all cryptographic and policy guarantees:
```cmd
python run_security_audit_tests.py
```
Expected output:
```text
======================================================================
  ENTERPRISE DATABASE BACKUP V5.0 - SECURITY & COMPLIANCE AUDIT
======================================================================
[TEST 1] Container Framing & Decryption:                 PASS
[TEST 2] AES-GCM Ciphertext Tamper Detection:            PASS
[TEST 3] Fail-Closed Escrow Policy:                      PASS
[TEST 4] Forbidden Secrets Sanitization:                 PASS
[TEST 5] Preflight Key Resolution:                       PASS
[TEST 6] RMM Status Telemetry JSON Schema:               PASS
----------------------------------------------------------------------
OVERALL AUDIT SCORE: 6 / 6 CHECKS PASSED (100% COMPLIANT)
======================================================================
```

---
*Enterprise Database Cloud Backup Automation v5.0.0 · System Setup Guide*
