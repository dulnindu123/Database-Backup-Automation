# 🏛️ System Architecture & Code Guide
### Enterprise Database Cloud Backup Automation · Version 5.0.0

**Classification:** Internal Engineering & Core Code Architecture Reference  
**App Version:** `v5.0.0` (November 2026 Post-Audit Release)  
**Security Standard:** Zero-Trust Cryptographic Enforcement  

---

## 📌 1. Architectural Overview

The system is a zero-trust backup architecture designed to securely upload encrypted database backups to Google Drive using a stateless Google Apps Script Broker API without storing cloud credentials on client endpoints.

### High-Level Topology

```mermaid
flowchart TD
    subgraph CustomerSites ["Customer Sites (70+ Deployments)"]
        C1["Client 1: DatabaseBackupApp"]
        C2["Client 2: Pure PowerShell Agent"]
        C3["Client 3: DatabaseBackupCLI"]
    end

    subgraph ServiceProviderCloud ["Cloud Infrastructure"]
        GAS["Google Apps Script Broker API\n(Code.gs)"]
        GS["Master Google Sheet\n(Tokens, Quotas, Audit & Telemetry)"]
        GD["Google Drive Enterprise Storage\n(Canonical Per-Tenant Folders)"]
        Sentinel["Missed-Backup Sentinel\n(Hourly SLA Health Checker)"]
    end

    subgraph AirGappedAdmin ["Disaster Recovery Infrastructure"]
        ADM["Air-Gapped Admin Workstation\n(decrypt_gui.py / decrypt_backup.py)"]
        PrivVault["Encrypted Offline Media\n(Primary & Escrow Private Keys)"]
    end

    C1 -->|1. JSON POST: Machine Auth / Request URI| GAS
    C2 -->|1. JSON POST: Machine Auth / Request URI| GAS
    C3 -->|1. JSON POST: Machine Auth / Request URI| GAS

    GAS <-->|2. Validate SHA-256 Token & Enforce Quota| GS
    GAS -->|3. Issue Resumable Upload URI| GD
    GAS -.->|4. Return Signed URI to Client| C1
    
    C1 ===>|5. Stream Encrypted Chunks Directly (8MB PUT)| GD
    Sentinel -->|6. Overdue SLA Alert (>26h)| AdminEmail["dulnindu@spillabs.com"]
    
    GD -.->|7. Download .dbk2 Ciphertext| ADM
    PrivVault -->|8. Decrypt Offline| ADM
```

---

## 💻 2. Component Code Architecture

### 2.1 Client-Side Core Engine (`backup_core.py`)
Runs on the customer machine to perform unattended backup operations:
- **Dumping**: Executes native Microsoft SQL Server backups using `COPY_ONLY` and `CHECKSUM` options via `sqlcmd.exe` or ODBC Driver 18.
- **Compression**: Streams dump data into `.zip` archive using Deflate Level 9 compression.
- **Framing & Encryption (`crypto_stream.py`)**: Wraps archive into `.dbk2` binary container using AES-256-GCM authenticated encryption. Ephemeral AES keys are wrapped via dual RSA-OAEP 4096-bit public keys (Primary + Tenant-Isolated Escrow).
- **Zero Client Secrets**: `scan_config_for_forbidden_secrets()` audits `config.json` and strips storage passwords and Gmail credentials from disk and memory.
- **External Credentials**: Resolves SQL authentication from ERP parameter files (`SQLPara.txt`) or Windows DPAPI local vaults (`secrets.dat`).
- **Policy Enforcement**: `fetch_and_cache_server_policy()` fetches signed security policies from the cloud broker and strictly prevents unencrypted execution.
- **Dual-Engine Alerting**: Alerts dispatch to Cloud Broker Sentinel first; transparently fails over to direct TLS SMTP (`smtp.gmail.com:587`) to `dulnindu@spillabs.com`.

### 2.2 Broker Client (`broker_client.py`)
Handles all communications between the client and Google Apps Script broker:
- Seamlessly resolves HTTP 302 redirects issued by Google Apps Script.
- Authenticates machine identity via SHA-256 token hashing.
- Exchanges chunks using HTTP `Content-Range` headers for resilient resumable uploads.

### 2.3 Cloud Broker Backend (`apps_script_broker/Code.gs`)
Stateless serverless gateway running in Google Apps Script:
- **`handleRequestUpload()`**: Authenticates machine token against `Tokens` tab in Google Sheets. Enforces destination folder strictly from the authenticated tenant identity (`destFolderId = canonicalFolderId`), completely ignoring client-supplied target folder IDs to eliminate Confused Deputy vulnerabilities.
- **`checkMissedBackups()`**: Hourly time-driven trigger scanning the `Tokens` tab for overdue backups (>26 hours since last successful upload). Dispatches automated SLA alert emails to `dulnindu@spillabs.com`.
- **`handleSendAlert()`**: Server-side alerting endpoint for dispatching high-priority operational and security alerts.

### 2.4 Disaster Recovery Suite (`Admin_Installation_Package/2_Disaster_Recovery/`)
Operates strictly on administrative hardware:
- **`decrypt_gui.py`**: Graphical wizard for selecting encrypted `.dbk2` archives, loading RSA-4096 private keys, and decrypting clean `.bak` files.
- **`decrypt_backup.py`**: High-performance command-line decryption utility.
- **`crypto_stream.py`**: Decryption implementation verifying 128-bit GCM MAC authentication tags, detecting ciphertext tampering, and validating archive headers.

### 2.5 Security Audit Test Suite (`run_security_audit_tests.py`)
Automated test suite verifying the 6 core security guarantees:
1. Container framing, header integrity, and decryption.
2. AES-256-GCM ciphertext tampering detection.
3. Fail-closed escrow policy enforcement.
4. Forbidden client secrets sanitization.
5. Preflight tenant escrow key resolution.
6. RMM status telemetry JSON schema validation.

---
*Enterprise Database Cloud Backup Automation v5.0.0 · Core Code Reference*
