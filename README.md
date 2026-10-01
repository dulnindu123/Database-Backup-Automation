# 🛡️ Enterprise Database Cloud Backup Automation (Zero-Trust Security Architecture v4.1.0)

<div align="center">
  <img src="docs_assets/app_icon.png" alt="Database Cloud Backup Logo" width="110">
  <br>
  <h3>Autonomous, Zero-Trust SQL Server Cloud Disaster Recovery & Telemetry System</h3>
  <p>
    <img src="https://img.shields.io/badge/Version-v4.1.0-blue?style=for-the-badge&logo=git&logoColor=white" alt="Version 4.1.0">
    <img src="https://img.shields.io/badge/Architecture-Zero--Trust%20Security%20Wall-0078D6?style=for-the-badge&logo=shield&logoColor=white" alt="Zero Trust">
    <img src="https://img.shields.io/badge/Encryption-AES--256--GCM%20%2B%20RSA--4096-green?style=for-the-badge&logo=lock&logoColor=white" alt="DBK2 Encryption">
    <img src="https://img.shields.io/badge/Cloud%20Run-Upload%20%26%20Telemetry%20Brokers-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white" alt="Cloud Run">
    <img src="https://img.shields.io/badge/Storage-Retention--Locked%20GCS%20Bucket-34A853?style=for-the-badge&logo=googlestorage&logoColor=white" alt="GCS Bucket">
  </p>
</div>

---

## 📌 Executive Security Overview

The **Enterprise Database Cloud Backup Automation System (v4.1.0)** is an air-gapped, zero-trust cloud disaster recovery solution for Microsoft SQL Server deployments.

### Security Wall Architecture
- **Zero Google Credentials on Client PCs**: Customer machines hold **no GCP service account keys, OAuth secrets, or credentials**. A compromised client machine cannot delete, read, list, or overwrite backups in Cloud Storage.
- **Client Authentication**: Authenticates strictly via native Windows DPAPI-protected per-PC Bearer token (`token.dpapi`) using `crypt32.dll` (`LocalMachine` scope `0x4`), with zero external dependencies.
- **DBK2 Streaming Hybrid Encryption**: Backups are encrypted locally using authenticated AES-256-GCM. The AES key is wrapped for dual 4096-bit RSA keys (Primary + Escrow). Private keys remain **offline** on administrative recovery hardware.
- **Upload Broker Microservice**: Exposes only `POST /request-upload` and `POST /verify`. Generates GCS resumable upload URIs for presigned, correctly named objects into a bucket with retention policy (permanently locked after the manual lock step). Enforces at least 3 upload slots per database per day (`{day}_{seq}.dbk2`), logging 409 duplicate events.
- **Telemetry Broker Microservice**: Receives server storage health reports, strictly validates 8 KB payloads, rate limits per PC, and appends rows to Google Sheets using `valueInputOption="RAW"` to prevent formula injection.
- **One-Command Automated Customer Provisioning**: Admins generate dedicated, zero-friction installer packages for each customer in seconds using `admin/build_customer_package.py`.

---

## ✨ Key Capabilities

- **🔐 Zero Secrets Client**: Client machines cannot read, list, or delete backups in Cloud Storage.
- **🔒 DBK2 Encrypted Archives**: Full hybrid stream encryption prior to transmission (atomic temp write, zero partial output on failure).
- **🖥️ Dedicated Scheduled Service**: Defaults to a dedicated standard user account following least privilege. `NT AUTHORITY\SYSTEM` in Session 0 is available as an opt-in for unattended operation across user logoffs.
- **⚡ Resumable Chunked Transfers**: Resumable stream directly to GCS with 10 exponential retries.
- **🛡️ MD5 Verification**: Local compressed files are deleted **only** after GCS returns an HTTP 200/201 response and the remote MD5 checksum matches the local file MD5 hash.
- **📊 Storage Telemetry & Email Alerts**: Real-time storage monitoring with DPAPI-encrypted SMTP credentials and automated alert emails.
- **📦 In-App Customer Integration**: Dedicated UI in Settings for customers to enter and validate their own Google Drive Folder ID and Master Google Sheet ID.

---

## 🏗 End-to-End Zero-Trust Architecture

```mermaid
flowchart TD
    subgraph ClientPC["Customer Machine (Zero Google Credentials)"]
        App["BackupApp / auto_backup.py"]
        Token["token.dpapi (Native Windows DPAPI)"]
        PubKey["backup_public.pem (RSA-4096 Public Key)"]
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

## 📦 Directory Structure

```text
BackupAutomation/
├── admin/
│   ├── build_customer_package.py    # 1-Command Automated Customer Installer & ZIP Generator
│   └── provision_pc.py              # Individual PC token generator & GCP Secret Manager register
├── app_gui.py                       # Desktop interface v4.1.0 (Zero-Trust Security Wall & Multi-Module)
├── audit_build.py                   # Automated distribution packaging & zero-leak security scanner
├── auto_backup.py                   # Command-line entrypoint & task router
├── backup_core.py                   # Backup orchestrator & DBK2 stream handler
├── broker/                          # Upload Broker microservice (Cloud Run)
├── broker_client.py                 # App-side HTTP client with native ctypes crypt32 DPAPI
├── build_executable.bat             # PyInstaller automated build pipeline
├── crypto_stream.py                 # DBK2 AES-256-GCM + RSA-4096 hybrid stream encryption
├── deploy.sh                        # Infrastructure-as-Code gcloud setup script
├── installer_gui.py                 # v4.1.0 Setup Wizard with live HTTP health checks & token ingestion
├── offline/
│   ├── decrypt_backup.py            # Air-gapped decryption utility
│   └── generate_keys.py             # Air-gapped RSA keypair generator
├── README.md                        # Master repository guide (v4.1.0)
├── RUNBOOK.md                       # Operational & disaster recovery runbook
├── SETUP.md                         # Deployment & configuration guide
├── telemetry_broker/                # Telemetry Broker microservice (Cloud Run)
└── tests/                           # 47 Automated Unit & Integration Tests (100% Pass)
```

---

## 🛠 Quick Start

### 1. Deploy Cloud Infrastructure
```bash
bash deploy.sh
```

### 2. Generate a Complete Customer Installation Package (One-Command)
```bash
python admin/build_customer_package.py --customer "CustomerName"
```
* Auto-fetches your live Cloud Run Upload Broker URL.
* Generates a cryptographic token and registers it into GCP Secret Manager.
* Creates `dist/packages/Client_Installation_Package_CustomerName.zip`.
* Broker URL and authentication are pre-configured; Google Drive and Sheet fields are left blank for the customer to input their own.

### 3. Customer Installation (Zero-Touch Client Experience)
1. Send the ZIP package to the customer.
2. The customer extracts the folder and runs **`Setup_DatabaseBackup.exe`** (or `1_Quick_Install.bat`).
3. The customer launches the application, opens the **Settings** tab, enters their **Google Drive Folder ID** and **Master Google Sheet ID**, and clicks **Save Settings**.

### 4. Run Automated Test Suite
```bash
python -m unittest discover -s tests -p "test_*.py"
```
*(47 / 47 tests passing)*
