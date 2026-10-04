# 🛡️ Enterprise Database Cloud Backup Automation System
# Technical Architecture, Engineering Documentation & Operational Runbook

**Document Version:** 4.1.0 (Zero-Trust Google Apps Script Edition)  
**Classification:** Confidential & Proprietary — Engineering, DevOps & Client Deployment Runbook  
**Target Operating Systems:** Windows 10, 11 | Windows Server 2016, 2019, 2022, 2025  
**Supported Database Engines:** Microsoft SQL Server 2012, 2014, 2016, 2017, 2019, 2022  
**Author / Chief Architect:** Dulnindu Saranga  

---

## 📌 1. Executive Summary & Zero-Trust Security Wall

The **Enterprise Database Cloud Backup Automation System (v4.1.0)** enforces a strict **Zero-Trust Security Wall** between customer PCs and Google Cloud infrastructure, using a zero-billing serverless architecture powered by Google Apps Script and Google Drive.

### Security Wall Principles
1. **Zero Client Secrets**: Customer PCs hold **no Google service account keys, cloud credentials, or OAuth secrets**. A compromised client machine cannot read, list, overwrite, or delete backups in Google Cloud Storage.
2. **DPAPI Machine-Scope Token Authentication**: Client PCs authenticate via a Windows DPAPI-encrypted machine token (`token.dpapi`), protected natively with Windows `CryptProtectData` (LocalMachine scope `0x4`).
3. **DBK2 Hybrid Envelope Encryption**: SQL Server database dumps are compressed into `.zip` and encrypted into streaming `.dbk2` format using authenticated AES-256-GCM. The ephemeral 256-bit AES symmetric key is wrapped using dual 4096-bit RSA keys (Primary `backup_public.pem` + Escrow `escrow_public.pem`). All RSA private decryption keys remain strictly **offline** on administrative hardware.
4. **Google Apps Script Web App Broker**: A dedicated Google Apps Script Web App that validates PC tokens, enforces upload limits, and returns pre-signed Google Drive Resumable Upload URIs. The client PC uploads directly to Google Drive without the broker acting as a bottleneck.
5. **Customer Multi-Module Telemetry & Tracking**: A Customer Master Google Sheet integrates all modules into dedicated tabs:
   - `Audit`: Logs every backup timestamp, database name, file size, SHA-256 hash, and upload status.
   - `Telemetry`: Storage monitor disk usage, health status, and space reclamation events.
6. **Single Unified Persistent Log**: All modules log chronologically to a single unified log file (`backup_log.txt`) stored at `C:\ProgramData\DatabaseBackupApp\backup_log.txt`. Historical logs are permanently preserved across updates.

---

## 🏗️ 2. Architectural Data Flow & Component Topology

```mermaid
graph TD
    %% Define Node Styles
    classDef client fill:#f9f9f9,stroke:#333,stroke-width:2px;
    classDef google fill:#fff,stroke:#4285F4,stroke-width:2px;
    classDef storage fill:#fff,stroke:#F4B400,stroke-width:2px;
    classDef admin fill:#fff,stroke:#DB4437,stroke-width:2px;
    
    subgraph Customer Sites
        C1[Client 1\nDatabaseBackupApp]:::client
        C2[Client 2\nDatabaseBackupApp]:::client
    end

    subgraph Google Workspace Cloud (Zero-Billing)
        GAS[Google Apps Script\nBroker API]:::google
        GS[Google Sheet\nTokens/Audit DB]:::google
        GD[Google Drive\nCustomer Storage]:::storage
    end
    
    subgraph Administration
        ADM[Air-Gapped Admin PC\npull_backup.py]:::admin
    end
    
    C1 -->|1. JSON POST: Enroll/Request URI| GAS
    C2 -->|1. JSON POST: Enroll/Request URI| GAS
    
    GAS <-->|2. Validate Token/Quota| GS
    GAS -->|3. Generate Resumable URI| GD
    GAS -.->|4. Return URI to Client| C1
    
    C1 ===>|5. Chunked HTTP PUT (Direct)| GD
    
    ADM --->|6. API Read-Only Pull| GD
```

---

## 🚀 3. Google Workspace Backend Setup (Administrator Guide)

Before installing the client, you must set up the Google Apps Script broker:

1. **Create the Master Google Sheet**:
   - Create a new Google Sheet.
   - Create 4 tabs exactly named: `Config`, `Tokens`, `Audit`, `Telemetry`.
   - In the `Config` tab, put `ENROLL_CODE` in cell A1, and your chosen secret password (e.g., `SuperSecret123`) in cell B1.
   - In the `Config` tab, put `TARGET_FOLDER_ID` in cell A2, and the Google Drive Folder ID where backups should land in cell B2.

2. **Deploy the Apps Script Web App**:
   - In the Google Sheet, go to **Extensions > Apps Script**.
   - Paste the code from `apps_script_broker/Code.gs` into the editor.
   - Click **Deploy > New deployment**.
   - Select **Web app**.
   - Execute as: **Me**.
   - Who has access: **Anyone**.
   - Click **Deploy** and copy the **Web App URL** (e.g., `https://script.google.com/macros/s/.../exec`).

---

## 🚀 4. Client Installation & Setup Workflows

### Method 1: Graphical Setup Wizard (`Setup_DatabaseBackup.exe`)
1. Run `Setup_DatabaseBackup.exe` as Administrator.
2. **Installation Destination**: Defaults to `C:\Program Files\DatabaseBackupApp`.
3. **Apps Script Web App URL**:
   - Paste the **Web App URL** generated in Step 3.
4. **Enrollment Code**:
   - Enter the `ENROLL_CODE` (e.g., `SuperSecret123`) you placed in your Google Sheet's Config tab.
5. Click `[Test Broker Connection]` to verify live connectivity with the endpoint.
6. Click `[Install Now]`. The installer:
   - Exchanges the Enrollment Code for a cryptographic machine token and seals it securely into Windows DPAPI storage.
   - Registers Windows Desktop and Start Menu shortcuts.
   - Registers the unattended Monday 02:00 AM backup schedule in Windows Task Scheduler.



---

## ⚙️ 5. Post-Installation Configuration & Token Management

Launch **Database Cloud Backup** and navigate to the **Settings** tab:

### Zero-Trust Security Wall & Token Import
- **Apps Script Web App URL**:
  - Displays your verified endpoint.
  - Locked by default (`🔒 Locked`). Click to confirm and unlock if endpoint changes are required.
- **Token Status**:
  - If a token is active: Displays `🔑 Token: Active (<pc_id>)` in green.
  - If missing: Displays `🔑 Token: MISSING (token.dpapi)` in red.
- **Connection Diagnostics**:
  - Click `[🔍 Test Broker Connection]` to test live TLS handshake, token authentication, and broker responsiveness.

---

## 📋 6. Restoring & Decrypting a Backup Offline

On an air-gapped recovery machine containing the private decryption key:
```bash
python decrypt_backup.py backup_20261001_1.dbk2 restored_backup.zip backup_private.pem [password]
```
If the primary private key is unavailable, use `escrow_private.pem` with the exact same syntax.

---
