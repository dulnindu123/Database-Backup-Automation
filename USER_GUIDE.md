# 🛡️ Enterprise Database Cloud Backup Automation System
# Technical Architecture, Engineering Documentation & Operational Runbook

**Document Version:** 4.1.0 (Zero-Trust Security Wall & Multi-Module Edition)  
**Classification:** Confidential & Proprietary — Engineering, DevOps & Client Deployment Runbook  
**Target Operating Systems:** Windows 10, 11 | Windows Server 2016, 2019, 2022, 2025  
**Supported Database Engines:** Microsoft SQL Server 2012, 2014, 2016, 2017, 2019, 2022  
**Author / Chief Architect:** Dulnindu Saranga  
**Last Revised & Verified:** October 2026  

---

## 📌 1. Executive Summary & Zero-Trust Security Wall

The **Enterprise Database Cloud Backup Automation System (v4.1.0)** enforces a strict **Zero-Trust Security Wall** between customer PCs and Google Cloud Platform infrastructure.

### Security Wall Principles
1. **Zero Client Secrets**: Customer PCs hold **no Google service account keys, cloud credentials, or OAuth secrets**. A compromised client machine cannot read, list, overwrite, or delete backups in Google Drive.
2. **Dedicated Cloud Run Broker Per Customer**: Each customer is provisioned with an isolated Cloud Run Upload Broker (`broker-<slug>`) and a dedicated service account limited via IAM conditions strictly to `projects/_/buckets/<bucket>/objects/<slug>/`. Cross-tenant token presentation is automatically rejected.
3. **Ed25519 Signed Manifest & Zero-Typing Installation**: Customer packages are cryptographically signed with an administrative Ed25519 key. The installer verifies the signature against an embedded public key. If verified, the broker URL is locked and the initial token is sealed into Windows DPAPI machine storage (`token.dpapi`) with **zero typing required from the customer**.
4. **Tamper Resistance**: If any file, endpoint URL, or manifest field is altered, the installer detects the mismatch (`ERR_MANIFEST_TAMPERED`), alerts the operator with a red warning banner, and aborts installation.
5. **DBK2 Hybrid Envelope Encryption**: SQL Server database dumps are compressed into `.zip` and encrypted into streaming `.dbk2` format using authenticated AES-256-GCM. The ephemeral 256-bit AES symmetric key is wrapped using dual 4096-bit RSA keys (Primary `backup_public.pem` + Escrow `escrow_public.pem`). All RSA private decryption keys remain strictly **offline** on administrative hardware.
6. **Customer Multi-Module Telemetry & Tracking**: Customer Master Google Sheet integrates all modules into dedicated tabs (`Backup Automation` | `Server Cleanup`).
7. **Single Unified Persistent Log**: All modules log chronologically to a single unified log file (`backup_log.txt`) stored at `C:\ProgramData\DatabaseBackupApp\backup_log.txt`. Historical logs are permanently preserved across updates.

---

## 🏗️ 2. Architectural Data Flow & Component Topology

```mermaid
flowchart TD
    subgraph ClientPC["Customer PC (Zero Google Credentials & Zero Typing)"]
        Manifest["manifest.json + manifest.sig<br/>(Ed25519 Signed Envelope)"]
        App["BackupApp / auto_backup.py"]
        Token["token.dpapi (Windows DPAPI Machine Scope)"]
        PubKey["backup_public.pem & escrow_public.pem"]
        Manifest -->|Verified at Install| Token
        App -->|1. Local SQL Backup & AES-256 Encrypt| DBK2["Encrypted Backup (.dbk2)"]
    end

    subgraph GCP["Google Cloud Platform (Dedicated Per-Customer Infrastructure)"]
        UploadBroker["Customer Upload Broker (Cloud Run)<br/>broker-<slug>.run.app<br/>roles/storage.objectCreator (<slug>/)"]
        TelemetryBroker["Telemetry Broker (Cloud Run)<br/>POST /report-storage<br/>roles/datastore.user"]
        GCS["GCS Bucket<br/>gs://backupbot-cold-archive/<slug>/<br/>(Retention Locked WORM)"]
        Sheets["Customer Master Google Sheet<br/>(Multi-Module Tabs)"]
        Drive["Customer Google Drive Folder<br/>(Direct Cloud DR Storage)"]
    end

    App -->|2. Request Upload Session (Bearer Token)| UploadBroker
    UploadBroker -->|3. Return Resumable Session URI| App
    App -->|4. Stream Encrypted DBK2 Payload| GCS
    App -->|5. Multi-Module Status Telemetry| TelemetryBroker
    TelemetryBroker -->|6. Append Formatted Rows| Sheets
```

---

## 🚀 3. Installation & Setup Workflows (Zero Typing Required)

### Method 1: Graphical Setup Wizard (`Setup_DatabaseBackup.exe`) — Recommended
1. Run `Setup_DatabaseBackup.exe` as Administrator.
2. **Automatic Manifest Verification**:
   - The installer verifies `manifest.json` and `manifest.sig` against the embedded Ed25519 administrator public key.
   - When verified, a green confirmation badge appears:  
     `🔒 AUTHENTIC ED25519 SIGNED PACKAGE (<CUSTOMER_SLUG>) - ZERO TYPING REQUIRED`
   - If tampered, a red alert banner appears (`⚠️ TAMPERED PACKAGE: ERR_MANIFEST_TAMPERED`) and installation is halted.
3. **Pre-Configured & Locked Parameters**:
   - **Upload Broker URL**: Pre-populated with your organization's dedicated endpoint (`https://broker-<slug>-...run.app`) and locked against accidental editing.
   - **Machine Authentication Token**: Automatically sealed from the signed manifest into Windows DPAPI machine-scope storage (`C:\ProgramData\DatabaseBackupApp\token.dpapi`).
   - The customer types nothing into these fields.
4. Click `[Install Now]`. The installer:
   - Copies all binaries, dependencies, and public encryption keys (`backup_public.pem`, `escrow_public.pem`).
   - Writes `%ProgramFiles%\DatabaseBackupApp\config.json`.
   - Hardens folder permissions via `icacls.exe`.
   - Registers Windows Desktop and Start Menu shortcuts.
   - Registers the unattended Monday 02:00 AM backup schedule in Windows Task Scheduler.

### Method 2: Automated Silent CLI (`1_Quick_Install.bat`)
- Run `1_Quick_Install.bat` from an elevated Command Prompt.
- Automatically verifies package files, seals DPAPI token, applies folder ACLs, and registers scheduled tasks with 0 user prompts.

---

## ⚙️ 4. Post-Installation Configuration & Verification

Launch **Database Cloud Backup** and navigate to the **Settings** tab:

### 4.1 Customer Cloud Integration (Google Drive & Sheets)
- **Customer Google Drive Folder ID or Link**:
  - Paste your customer's dedicated Google Drive folder URL or 33+ character folder ID.
  - The UI displays live validation: `✓ Valid Drive Folder ID Format`.
  - Click `[Open Folder ->]` to verify direct access in your browser.
- **Customer Master Google Sheet ID or Link**:
  - Paste your customer's Master Google Sheet URL or 44-character spreadsheet ID.
  - The UI displays live validation: `✓ Valid Sheet ID Format`.
  - Click `[Open Sheet ->]` to verify access in your browser.
  - Automatically writes telemetry to separate module tabs:
    `Backup Automation` | `Server Cleanup`.

### 4.2 Zero-Trust Security Wall & Verification
- **Upload Broker URL**:
  - Displays your verified, dedicated Cloud Run endpoint (`https://broker-<slug>-...`).
  - Pre-configured and locked (`🔒 Locked`).
- **Token Status**:
  - Displays `🔑 Token: Active (<slug>-pc01)` in green.
- **Public Encryption Key**:
  - Displays `🔒 Public Key: Present (backup_public.pem)` in green.
- **Connection Diagnostics**:
  - Click `[🔍 Test Broker Connection]` to test live TLS handshake, token authentication, and broker responsiveness.

---

## 📋 5. Administration & Operational Runbook

### 5.1 Automated Customer Onboarding (Recommended: 1 Single Command)
On your administrator machine, run:
```bash
python admin/build_customer_package.py --customer "CustomerName"
```
#### Automated Pipeline:
1. **Auto-Fetches** your live Cloud Run Upload Broker URL via `gcloud`.
2. **Generates** a cryptographically secure token `<pc_id>.<secret>`.
3. **Registers** the token hash into Google Secret Manager (`pc-tokens`) automatically.
4. **Builds** a dedicated customer package: `dist/packages/Client_Installation_Package_CustomerName.zip`.
5. Pre-configures the Broker URL and bundles `raw_token.txt` (which is encrypted into DPAPI and shredded on customer install).
6. **Leaves Google Drive & Sheet IDs empty** so the customer can enter their own credentials in the application.

### 5.2 Standalone Token Provisioning (Manual Workstation Fallback)
If generating tokens manually for an existing installation:
```bash
python admin/provision_pc.py --pc-id pc-customer-01
```
Output:
1. `raw_token.txt`: Place next to the customer installer or import in the application GUI.
2. `HASH`: Add to Secret Manager `pc_tokens.json` in Google Cloud.

### 5.3 Restoring & Decrypting a Backup Offline
On an air-gapped recovery machine containing the private decryption key:
```bash
python decrypt_backup.py backup_20261001_1.dbk2 restored_backup.zip backup_private.pem [password]
```
If the primary private key is unavailable, use `escrow_private.pem` with the exact same syntax.

### 5.4 Single Unified Persistent Audit Log
- All operations are appended to:
  `C:\ProgramData\DatabaseBackupApp\backup_log.txt`
- Log format:
  `YYYY-MM-DD HH:MM:SS [MODULE] [LEVEL] Message text`
- Module tags: `[BACKUP]`, `[CLEANUP]`, `[PERF_QUERY]`, `[SYSTEM]`
- View logs live in the **Live Logs** tab inside the application.
