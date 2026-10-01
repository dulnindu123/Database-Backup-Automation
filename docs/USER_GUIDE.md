# 🛡️ Enterprise Database Cloud Backup Automation System
# Technical Architecture, Engineering Documentation & Operational Runbook

**Document Version:** 4.0.0 (Zero-Trust Security Wall Edition)  
**Classification:** Confidential & Proprietary — Engineering, DevOps & Client Deployment Runbook  
**Target Operating Systems:** Windows 10, 11 | Windows Server 2016, 2019, 2022, 2025 *(Windows 7, 8, 8.1 and Server 2008 R2 / 2012 marked as legacy/untested; macOS and Linux are unsupported)*  
**Supported Database Engines:** Microsoft SQL Server 2012, 2014, 2016, 2017, 2019, 2022 *(SQL Server 2000 and 2005 marked as legacy/untested)*  
**Author / Chief Architect:** Dulnindu Saranga  
**Last Revised & Verified:** October 2026  

---

## 📌 1. Executive Summary & Zero-Trust Security Wall

The **Enterprise Database Cloud Backup Automation System (v4.0.0)** enforces a strict **Zero-Trust Security Wall** between customer PCs and Google Cloud Platform infrastructure.

### Security Wall Architecture
1. **Zero Client Secrets**: Customer PCs hold **no Google credentials, service account keys, or OAuth secrets**. A compromised client PC cannot read, list, overwrite, or delete backups in Google Cloud Storage.
2. **DPAPI Machine Token Authentication**: Client PCs authenticate via a Windows DPAPI-encrypted machine token (`token.dpapi`), protected with `CryptProtectData` (LocalMachine scope).
3. **DBK2 Hybrid Encryption**: SQL Server database dumps are compressed and encrypted locally using streaming AES-256-GCM before transmission. The 256-bit AES key is wrapped using dual 4096-bit RSA keys (Primary + Escrow). All RSA private keys remain **offline** on administrative hardware.
4. **Upload Broker Microservice**: Dedicated Cloud Run service (`upload-broker`) that validates requests, enforces database names, size caps, and provides at least 3 upload slots per database per day (`{day}_{seq}.dbk2`), returning presigned GCS resumable upload URIs.
5. **Telemetry Broker Microservice**: Dedicated Cloud Run service (`telemetry-broker`) that receives drive health telemetry, validates schema and bounds, rate-limits submissions per PC, and appends rows to a monitoring Google Sheet using `valueInputOption="RAW"` to prevent formula injection.
6. **Retention-Locked Storage**: Backups are stored in a GCS bucket with Uniform Bucket-Level Access and object retention policy (permanently locked into WORM mode after administrator executes the manual lock step).

---

## 🏗️ 2. Architectural Data Flow & Component Topology

```mermaid
flowchart TD
    subgraph ClientPC["Customer PC (Zero Google Credentials)"]
        App["BackupApp / auto_backup.py"]
        Token["token.dpapi (DPAPI Protected)"]
        PubKey["backup_public.pem & escrow_public.pem"]
        App -->|1. SQL Backup & DBK2 Encrypt| DBK2["Encrypted Backup (.dbk2)"]
    end

    subgraph GCP["Google Cloud Platform (Admin Controlled)"]
        UploadBroker["Upload Broker (Cloud Run)<br/>POST /request-upload<br/>roles/storage.objectCreator"]
        TelemetryBroker["Telemetry Broker (Cloud Run)<br/>POST /report-storage<br/>roles/datastore.user"]
        GCS["GCS Bucket<br/>(Retention Locked WORM)"]
        Sheets["Monitoring Google Sheet<br/>(Append-Only RAW)"]
    end

    App -->|2. Request Upload Session (Bearer Token)| UploadBroker
    UploadBroker -->|3. Return Resumable GCS URI| App
    App -->|4. Stream Encrypted Payload| GCS
    App -->|5. Report Drive Telemetry| TelemetryBroker
    TelemetryBroker -->|6. Append Row| Sheets
```

---

## 🔐 3. Component Details & Security Responsibilities

### 3.1 Upload Broker (`upload-broker`)
- **Container**: `broker/Dockerfile` running Flask + Gunicorn on Cloud Run.
- **Identity**: `upload-broker@$PROJECT.iam.gserviceaccount.com` (holds `roles/storage.objectCreator` on the GCS bucket only, never `objectAdmin`).
- **API Surface**:
  - `POST /request-upload`: Authenticates Bearer token (`pc_id.secret`), validates payload, enforces 3-slot daily limit (`{day}_{seq}.dbk2`), and generates GCS resumable upload session URI (`if_generation_match=0`).
  - `POST /verify`: Non-consuming validation probe for GUI connection testing.
  - `GET /healthz`: Liveness probe.
- **Security Rule**: Exposes **no** list, read, download, delete, or client-chosen path endpoints.

### 3.2 Telemetry Broker (`telemetry-broker`)
- **Container**: `telemetry-broker/Dockerfile` running Flask + Gunicorn on Cloud Run.
- **Identity**: `telemetry-broker@$PROJECT.iam.gserviceaccount.com` (holds `roles/datastore.user` for Firestore rate-limiting and Google Sheets append access).
- **API Surface**:
  - `POST /report-storage`: Validates 8 KB payload cap, Bearer token, 1..26 drives, drive name regex (`^[A-Z]:\\?$`), drive type enum, numeric bounds (`0 <= free <= total`, `0 <= percent <= 100`), and appends telemetry to tab `[pc_id]!A:G` using `valueInputOption="RAW"`.
  - Rate limiting (1 report / 15 min per `pc_id`) via Firestore with in-memory fallback.

### 3.3 DBK2 Hybrid Encryption Format
- **Magic Header**: `DBK2` (4 bytes ASCII), Version `0x01` (1 byte), Num Recipients `1..8` (1 byte).
- **Per Recipient**: 8-byte SHA-256 fingerprint + 2-byte big-endian key length + RSA-OAEP wrapped AES-256 key (minimum 3072-bit, default 4096-bit).
- **Nonce Prefix**: 8 bytes random. Chunk nonce = prefix (8B) + 4-byte big-endian counter.
- **Streaming Chunks**: Repeated `[4-byte BE uint32 len] [AES-256-GCM ciphertext]` chunks. AAD per chunk binds `SHA-256(Header) + terminal_flag (1B) + counter (4B)`.
- **Atomic File Output**: Temporary file (`dst + ".tmp"`) is unlinked immediately on any MAC/tamper error. Zero partial output is left on disk upon failure.

---

## 🛠️ 4. Administration & Operational Runbook

### 4.1 Token Provisioning & Secure Transfer Workflow
Because Windows DPAPI encrypts secrets using the local machine's LSA keys, DPAPI tokens **cannot** be generated on an admin machine and copied to a customer PC.

1. On the Administrator workstation:
   ```bash
   python admin/provision_pc.py --pc-id pc-customer-01
   ```
   This generates `raw_token.txt` and outputs the token hash for Secret Manager (`pc_tokens.json`).
2. Securely transfer `raw_token.txt` to the customer PC (via encrypted USB drive, SCP, or secure admin share).
3. Place `raw_token.txt` alongside `1_Quick_Install.bat` or `Update_App.bat`.
4. Run the installer script on the customer PC. It automatically encrypts the token using local Windows DPAPI (LocalMachine scope) into `token.dpapi`, and immediately overwrites and wipes `raw_token.txt`.

### 4.2 Restoring & Decrypting a Backup Offline
On an air-gapped recovery machine with private keys:
```bash
python offline/decrypt_backup.py backup_20261001_1.dbk2 restored_backup.zip backup_private.pem [password]
```
If the primary private key is unavailable, use `escrow_private.pem` with the same syntax.

### 4.3 Upload Slot Rules & Stolen Token Slot-Burning Mitigation
- The broker allocates at least 3 upload slots per database per day (`_1.dbk2`, `_2.dbk2`, `_3.dbk2`).
- If an earlier slot is occupied, the client retries the next slot, logging:
  `Upload slot X/3 for database '<db>' is already used today (HTTP 409 Conflict)`.
- **Slot Burning Threat**: If an attacker steals `token.dpapi`, they cannot delete or view past backups, but they can burn the 3 slots for today by uploading dummy files.
- **Detection**: Cloud Logging alerts on `jsonPayload.event="duplicate"`; client logs a critical security alert if all 3 slots are exhausted.
- **Mitigation**:
  1. Revoke the token immediately by removing its entry from `pc_tokens.json` in Secret Manager. *(Revocation propagates in a few minutes when Cloud Run volume syncs)*.
  2. Re-provision a fresh token via `python admin/provision_pc.py --pc-id pc-customer-01`.
  3. Deploy the new token to the customer PC using the secure transfer workflow.

### 4.4 Task Scheduler Privilege Configuration
- **Default (Dedicated User Account)**: The installer configures the scheduled backup under the currently active user account, adhering to the principle of least privilege.
- **Opt-in (NT AUTHORITY\\SYSTEM)**: For unattended server installations where backups must run across interactive user logoffs and reboots without user sign-in, administrators can configure the task to run under `NT AUTHORITY\SYSTEM` with `/rl HIGHEST`.


---

## 5. End-to-End Application Configuration Guide (Field-by-Field Reference)

This section provides complete instructions on how to fill in all configuration fields across the application to achieve a 100% runnable setup.

---

### 5.1 Tab 3: Settings (Core Database & Cloud Parameters)

| Field Label | Purpose | Where to Get It / How to Fill |
| :--- | :--- | :--- |
| **SQL Server Instance Name** | Network address or named instance of your Microsoft SQL Server. | • **Automatic:** Click the **`Auto-Detect`** button right next to the field.<br>• **Default Local Instance:** Enter `.` or `localhost`<br>• **Named Instance (e.g. SQLEXPRESS):** Enter `localhost\SQLEXPRESS` or `DESKTOP-NAME\SQLEXPRESS`.<br>• *How to verify manually:* Open Windows Services (`services.msc`) and look for `SQL Server (MSSQLSERVER)` or `SQL Server (INSTANCENAME)`. |
| **SQL Username & Password** *(optional)* | Credentials used to authenticate to SQL Server. | • **Windows Authentication (Recommended):** Leave **BOTH fields completely blank**.<br>• **SQL Server Authentication:** If your database server requires SQL logins, enter `sa` (or dedicated backup user) and its password. |
| **Target Databases (separated by commas)** | Specific databases to back up. | • **Automatic:** When you click `Auto-Detect`, the application lists all user databases.<br>• **Manual:** Open SQL Server Management Studio (SSMS) or run `sqlcmd -Q "SELECT name FROM sys.databases WHERE database_id > 4"`.<br>• **Format:** Enter database names separated by commas (e.g. `SuperForm, GeelongGlass, ERP_Production`). Do not include system databases like `tempdb` or `master`. |
| **Local Backup Folder** | Temporary staging folder where SQL Server writes `.bak` dumps prior to DBK2 encryption. | • Click **`Browse...`** to pick a folder on a drive with adequate free disk space (e.g., `C:\temp\backups` or `D:\DatabaseBackups`).<br>• The application automatically grants SQL Server Service permissions to this folder when saved. |
| **Upload Broker URL** | Cloud Run endpoint for Zero-Trust presigned uploads. | • **Local Testing / Development:** `http://127.0.0.1:5000`<br>• **Production:** Enter the HTTPS URL provided after running `deploy.sh` on Google Cloud (e.g., `https://upload-broker-xxxx-uc.a.run.app`). |
| **Customer Google Drive Folder ID / Link** | Dedicated customer Google Drive folder for cloud backup storage and archives. | • Open Google Drive in your web browser, navigate to the customer folder, and copy the browser URL or folder ID.<br>• *Example URL:* `https://drive.google.com/drive/folders/1LKuo7j4cHvvP0-p0C6PVo6gdkgoVBaQ4`<br>• *Example ID:* `1LKuo7j4cHvvP0-p0C6PVo6gdkgoVBaQ4`<br>• Click **`Open Folder ↗`** in the application to test the link directly. |
| **Customer Master Google Sheet ID / Link** | Master tracking spreadsheet for the customer containing the 3 module tabs. | • Open the customer's Google Spreadsheet in your web browser and copy the URL or ID.<br>• *Example URL:* `https://docs.google.com/spreadsheets/d/1FAnmfTAixeDgwA5f3TvJ9IEtFp1OuFTyw3UpDiOdvwg/edit`<br>• *Example ID:* `1FAnmfTAixeDgwA5f3TvJ9IEtFp1OuFTyw3UpDiOdvwg`<br>• Inside this spreadsheet, ensure 3 worksheet tabs exist:<br>&nbsp;&nbsp;1. `Backup Automation`<br>&nbsp;&nbsp;2. `Server Cleanup`<br>&nbsp;&nbsp;3. `Performance Query`<br>• Click **`Open Sheet ↗`** in the application to test the link directly. |
| **Delete local backup file after upload** | Storage optimization toggle. | • Keep this **checked [✓]** so that the local unencrypted `.bak` file is safely deleted after successful encrypted upload to the cloud. |

---

### 5.2 Tab 5: Server Health (Email Alert Configuration)

When storage alerts are triggered (e.g., C: drive free space drops below threshold or data drives exceed usage), high-priority email alerts are automatically dispatched.

| Field Label | Purpose | Where to Get It / How to Fill |
| :--- | :--- | :--- |
| **Recipient Email** | The destination email address that will receive the critical alerts. | • Enter the IT support or administrator email (e.g. `support@spillabs.com` or `admin@yourcompany.com`). |
| **Sender Email** | The mailbox used by the application to send automated notification emails. | • Enter an Outlook.com, Microsoft 365, or Gmail address (e.g. `alerts-backup@spillabs.com` or `companybackup@outlook.com`). |
| **Sender Password** | Authentication credential for the SMTP sender account. | • **IMPORTANT:** If Multi-Factor Authentication (MFA / 2FA) is enabled on the sender account, you **must use an App Password**, not your normal login password.<br>• **How to generate an Outlook/Microsoft 365 App Password:**<br>&nbsp;&nbsp;1. Sign in to your Microsoft Account security page: `https://account.microsoft.com/security`.<br>&nbsp;&nbsp;2. Go to **Advanced Security Options** -> **App Passwords**.<br>&nbsp;&nbsp;3. Click **Create a new app password** and paste the 16-character code here.<br>• **How to generate a Gmail App Password:**<br>&nbsp;&nbsp;1. Go to `https://myaccount.google.com/apppasswords`.<br>&nbsp;&nbsp;2. Select App: *Mail*, Device: *Windows Computer*, generate and paste the 16-character code. |
| **SMTP Server** | Mail server hostname. | • **Outlook / Hotmail:** `smtp-mail.outlook.com`<br>• **Microsoft 365 Business:** `smtp.office365.com`<br>• **Gmail:** `smtp.gmail.com` |
| **SMTP Port** | TLS / STARTTLS secure transmission port. | • Set to **`587`** (Default for TLS / STARTTLS). |
| **C: Drive Threshold (GB)** | Minimum free gigabytes before firing an alert. | • Default: `30` (Alerts if C: drive has less than 30 GB free space). |
| **Other Drives Threshold (%)** | Maximum percentage utilized before firing an alert. | • Default: `90` (Alerts if D:, E:, or network drives reach 90% full). |

---

### 5.3 Step-by-Step Verification Runbook (Making the App Runnable)

Follow these 4 steps after entering the configuration:

1. **Step 1: Save Parameters:**
   - In Tab 3 (`Settings`), click **`💾 Save Settings`**.
   - In Tab 5 (`Server Health`), click **`💾 Save Storage Monitor Settings`**.
2. **Step 2: Test Cloud Broker Connectivity:**
   - In Tab 3 (`Settings`), click **`🔍 Test Broker Connection`**.
   - Verify that the status pop-up reports a successful HTTP 200 connection to the Upload Broker.
3. **Step 3: Execute a Test Backup:**
   - Go to Tab 1 (`Dashboard`).
   - Click **`▶ Run Full Backup Now`**.
   - Switch to Tab 4 (`Live Logs`) to monitor real-time execution. Verify that SQL Server creates the backup, DBK2 encryption completes, and the upload succeeds.
4. **Step 4: Enable Automated Schedule:**
   - Go to Tab 2 (`Auto Schedule`).
   - Select your schedule frequency (e.g. `Weekly (Mondays)` or `Daily`) and preferred execution time (e.g. `02:00`).
   - Click **`Save & Enable Schedule`** to register the automated background job in Windows Task Scheduler.
