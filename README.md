# 🛡️ Enterprise Database Cloud Backup Automation (Zero-Trust Security Architecture v4.0.0)

<div align="center">
  <img src="docs_assets/app_icon.png" alt="Database Cloud Backup Logo" width="110">
  <br>
  <h3>Autonomous, Zero-Trust SQL Server Cloud Disaster Recovery & Telemetry System</h3>
  <p>
    <img src="https://img.shields.io/badge/Architecture-Zero--Trust%20Security%20Wall-0078D6?style=for-the-badge&logo=shield&logoColor=white" alt="Zero Trust">
    <img src="https://img.shields.io/badge/Encryption-AES--256--GCM%20%2B%20RSA--4096-green?style=for-the-badge&logo=lock&logoColor=white" alt="DBK2 Encryption">
    <img src="https://img.shields.io/badge/Cloud%20Run-Upload%20%26%20Telemetry%20Brokers-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white" alt="Cloud Run">
    <img src="https://img.shields.io/badge/Storage-Retention--Locked%20GCS%20Bucket-34A853?style=for-the-badge&logo=googlestorage&logoColor=white" alt="GCS Bucket">
  </p>
</div>

---

## 📌 Executive Security Overview

The **Enterprise Database Cloud Backup Automation System (v4.0.0)** is an air-gapped, zero-trust cloud disaster recovery solution for Microsoft SQL Server deployments.

### Security Wall Architecture
- **Zero Google Credentials on Client PCs**: Customer machines hold **no GCP service account keys, OAuth secrets, or credentials**. A compromised client machine cannot delete, read, list, or overwrite backups in Cloud Storage.
- **Client Authentication**: Authenticates strictly via a DPAPI-protected per-PC Bearer token (`token.dpapi`), bound to the local machine.
- **DBK2 Streaming Hybrid Encryption**: Backups are encrypted locally using AES-256-GCM. The AES key is wrapped for dual 4096-bit RSA keys (Primary + Escrow). Private keys remain **offline** on administrative recovery hardware.
- **Upload Broker Microservice**: Exposes only `POST /request-upload` and `POST /verify`. Generates GCS resumable upload URIs for presigned, correctly named objects into a bucket with retention policy (permanently locked after the manual lock step). Enforces at least 3 upload slots per database per day (`{day}_{seq}.dbk2`), logging 409 duplicate events.
- **Telemetry Broker Microservice**: Receives server storage health reports, strictly validates 8 KB payloads, rate limits per PC, and appends rows to Google Sheets using `valueInputOption="RAW"` to prevent formula injection.

---

## ✨ Key Capabilities

- **🔐 Zero Secrets Client**: Client machines cannot read, list, or delete backups in Cloud Storage.
- **🔒 DBK2 Encrypted Archives**: Full hybrid stream encryption prior to transmission (atomic temp write, zero partial output on failure).
- **🖥️ Dedicated Scheduled Service**: Defaults to a dedicated standard user account following least privilege. `NT AUTHORITY\SYSTEM` in Session 0 is available as an opt-in for unattended operation across user logoffs.
- **⚡ Resumable Chunked Transfers**: Resumable stream directly to GCS with 10 exponential retries.
- **🛡️ MD5 Verification**: Local compressed files are deleted **only** after GCS returns an HTTP 200/201 response and the remote MD5 checksum matches the local file MD5 hash.
- **📊 Storage Telemetry & Email Alerts**: Real-time storage monitoring with DPAPI-encrypted SMTP credentials and automated alert emails.

---

## 🏗 End-to-End Zero-Trust Architecture

```mermaid
flowchart TD
    subgraph ClientPC["Customer Machine (Zero Google Credentials)"]
        App["BackupApp / auto_backup.py"]
        Token["token.dpapi (DPAPI Protected)"]
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
│   └── provision_pc.py              # PC Provisioning tool for admins
├── app_gui.py                       # Desktop interface (Zero-Trust Security Wall)
├── auto_backup.py                   # Command-line entrypoint & task router
├── backup_core.py                   # Backup orchestrator & DBK2 stream handler
├── broker/                          # Upload Broker microservice (Cloud Run)
├── broker_client.py                 # App-side HTTP client for Upload & Telemetry Brokers
├── build_executable.bat             # PyInstaller build script with build-time secret guard
├── crypto_stream.py                 # DBK2 AES-256-GCM + RSA-4096 hybrid stream encryption
├── deploy.sh                        # Infrastructure-as-Code gcloud setup script
├── installer_gui.py                 # Installation wizard & ACL security hardener
├── offline/
│   ├── decrypt_backup.py            # Air-gapped decryption utility
│   └── generate_keys.py             # Air-gapped RSA keypair generator
├── README.md                        # Master repository guide
├── RUNBOOK.md                       # Operational & disaster recovery runbook
├── SETUP.md                         # Deployment & configuration guide
├── telemetry_broker/                # Telemetry Broker microservice (Cloud Run)
└── tests/
    └── test_telemetry_broker.py     # Offline automated unit test suite
```

---

## 🛠 Quick Start

1. **Deploy GCP Cloud Infrastructure**:
   ```bash
   bash deploy.sh
   ```
2. **Provision Customer PC**:
   ```bash
   python admin/provision_pc.py --pc-id pc-customer-01
   ```
3. **Build Executable (with Secret Guard Check)**:
   ```bash
   build_executable.bat
   ```
4. **Run Unit Tests**:
   ```bash
   python -m unittest discover -s tests -p "test_*.py"
   ```
