# 🛡️ Enterprise Database Cloud Backup Automation
### Zero-Trust Disaster Recovery & Multi-Tenant Telemetry Suite · v5.0.0

<div align="center">
  <img src="docs/images/app_icon.png" alt="Logo" width="110">
  <br>
  <p>
    <img src="https://img.shields.io/badge/Version-v5.0.0--20261108-blue?style=for-the-badge&logo=git&logoColor=white">
    <img src="https://img.shields.io/badge/Architecture-Zero--Trust%20Cloud%20Broker-059669?style=for-the-badge&logo=googlecloud&logoColor=white">
    <img src="https://img.shields.io/badge/Encryption-AES--256--GCM%20%2B%20RSA--4096-green?style=for-the-badge&logo=lock&logoColor=white">
    <img src="https://img.shields.io/badge/Escrow-Isolated%20Per--Tenant%20Keys-blueviolet?style=for-the-badge&logo=security&logoColor=white">
    <img src="https://img.shields.io/badge/Shell%20Agent-100%25%20Pure%20PowerShell-239120?style=for-the-badge&logo=powershell&logoColor=white">
    <img src="https://img.shields.io/badge/Client%20Python-NOT%20REQUIRED-success?style=for-the-badge&logo=windows&logoColor=white">
    <img src="https://img.shields.io/badge/Security%20Audit-100%25%20PASSED-brightgreen?style=for-the-badge&logo=checkmarx&logoColor=white">
  </p>
  <h3>Autonomous, Zero-Knowledge Disaster Recovery for Microsoft SQL Server</h3>
  <p>
    <b>📘 Definitive Master Manual:</b> <a href="ENTERPRISE_DATABASE_BACKUP_V5_MASTER_SPECIFICATION_AND_MANUAL.docx"><b>Word (.docx)</b></a> · <a href="ENTERPRISE_DATABASE_BACKUP_V5_MASTER_SPECIFICATION_AND_MANUAL.pdf"><b>Adobe PDF (.pdf)</b></a><br>
    <b>📊 Executive Technical Report:</b> <a href="EXECUTIVE_TECHNICAL_REPORT_V5_COMPREHENSIVE_UPGRADES.pdf"><b>Senior Technical Report (.pdf)</b></a> |
    <b>📄 Client Installation Guide:</b> <a href="docs/INSTALLATION_GUIDE_v5.0.docx"><b>Field Manual (.docx)</b></a> |
    <b>🏛️ System Walkthrough:</b> <a href="docs/ENTERPRISE_DATABASE_CLOUD_BACKUP_V5_COMPLETE_SYSTEM_WALKTHROUGH.docx"><b>Architecture Walkthrough (.docx)</b></a>
  </p>
</div>

---

## 📌 Executive Overview

**Enterprise Database Cloud Backup Automation (v5.0.0)** is an enterprise-grade, zero-trust automated disaster recovery system engineered to protect mission-critical Microsoft SQL Server databases across 70+ customer deployments.

The architecture enforces strict client-side cryptographic isolation: customer endpoints hold public keys only and can never decrypt stored archives; all uploads route through a stateless serverless Google Cloud Broker; and all administrative recovery tools operate strictly air-gapped from production environments.

### 🌟 Flexible Deployment Tracks
* **Track 1: Graphical Setup Wizard (`Setup_DatabaseBackup.exe`)**: One-click, zero-typing modern graphical installer and interactive desktop control panel (`DatabaseBackupApp.exe`). Automatically provisions DPAPI machine-scope tokens, validates Ed25519 digital signatures, configures Windows Scheduled Tasks (`Database Cloud Backup`), and provides visual status dashboards.
* **Track 2: Pure PowerShell Shell Agent (`shell_client/`)**: **Zero Python dependencies, zero third-party binaries, under 30 KB footprint**. Uses native Windows OS-level .NET Cryptography (`RSACng`, `AesGcm`) and DPAPI (`token.dpapi`). Purpose-built for locked-down database servers, headless Windows Server Core, and vintage environments (Windows Server 2008 R2 SP1+).
* **Track 3: Command-Line Interface (`DatabaseBackupCLI.exe`)**: Standalone, auditable headless console utility for administrative batch orchestration, DevOps pipelines, and continuous integration.

---

## 🏛️ Comprehensive Architectural Framework

### 1. The 9 Senior Architectural Upgrades
| # | Upgrade Specification | Technical Implementation & Rationale |
| :--- | :--- | :--- |
| **1 & 7** | **Customer-Dedicated Drive Folders** | Backups route strictly to tenant-isolated Google Drive folders (`canonicalFolderId`), eliminating quota collisions and cross-tenant visibility. |
| **2** | **Enterprise Fleet Quota & Monitoring** | Standardized on Google Workspace / Shared Drive enterprise infrastructure with automated headroom telemetry, replacing consumer storage limits. |
| **3** | **Dynamic `bundle.json` Retrieval** | Ingests signed configuration bundles dynamically in-memory via Google Drive share link/ID, eliminating static disk secrets. |
| **4** | **Per-Tenant Escrow Key Isolation** | Replaced global master escrow with tenant-isolated RSA-4096 escrow keys (`escrow_public_{slug}.pem`), strictly limiting key compromise blast radius. |
| **5** | **Mandatory Encryption & Remote Policy** | Encryption cannot be disabled without operator override confirmation and immediate multi-channel administrative alerting; verified against server-side signed policy. |
| **6** | **Externalized SQL Credentials** | Plaintext database credentials completely removed from `config.json`. Credentials resolve dynamically from ERP parameter files (`SQLPara.txt`) or Windows DPAPI local vaults (`secrets.dat`). |
| **8** | **Intelligent Tiered SQL Maintenance** | Deprecated `DBCC DBREINDEX` replaced with dynamic SQL: **<5% skip**, **5–30% reorganize online** (0% locking, zero ERP downtime), **>30% rebuild off-peak** (19:00–07:00). |
| **9** | **Standardized Technical Terminology** | Marketing hyperbole purged across all code, manuals, and interfaces; standardized on exact cryptographic standards (AES-256-GCM, RSA-4096, SHA-256). |

### 2. The 8 November 2026 Audit Hardening Upgrades
| Finding | Security & Operational Enhancement | Implementation Details |
| :--- | :--- | :--- |
| **F-01** | **Server-Side Folder Enforcement** | Cloud broker resolves `destFolderId = canonicalFolderId` strictly from authenticated token hash. Client-supplied `target_folder_id` is completely ignored and logged as `SECURITY_FOLDER_OVERRIDE_IGNORED`. |
| **F-02** | **Fail-Closed Escrow Preflight** | `preflight.py` aligns dynamically to check `escrow_public_{customer_slug}.pem` (the identical file used at runtime) and halts backup execution if the key is missing. |
| **F-03** | **Zero Client Secrets Enforcement** | `scan_config_for_forbidden_secrets()` automatically strips `STORAGE_ALERT_SENDER_PASSWORD`, `GMAIL_APP_PASSWORD`, and webhook secrets from both memory and disk on startup. |
| **F-04** | **Missed-Backup Sentinel (SLA Engine)** | Hourly Google Apps Script trigger (`checkMissedBackups()`) evaluates database backup freshness (>26 hours) and dispatches automated SLA alerts to `dulnindu@spillabs.com`. |
| **F-05** | **Air-Gapped Key Custody** | Offline private keys migrated outside OneDrive-synced file trees to dedicated physical media with hardware BitLocker protection. |
| **F-06** | **Remote Signed Security Policy** | Client pulls signed policy via `fetch_and_cache_server_policy()` on each run (7-day local cache); rejects unencrypted backup if policy enforces encryption. |
| **F-07** | **Dual-Engine Alert Transport** | Cloud Broker Sentinel acts as primary alert transport; transparently fails over to direct TLS SMTP (`smtp.gmail.com:587`) for guaranteed alerting during broker downtime. |
| **F-08** | **Automated Security Audit Suite** | Standalone automated test suite (`run_security_audit_tests.py`) verifying encryption framing, GCM tampering detection, escrow fail-closed policies, and restore drills with **100% pass rate**. |

---

## 🔒 Zero-Trust Anti-Ransomware Topology

```mermaid
flowchart TD
    subgraph ClientHost [Client Database Server]
        SQL[("Microsoft SQL Server\n(2005 - 2022)")]
        CoreEngine["Backup Engine\n(GUI or PowerShell)"]
        DPAPI["Windows DPAPI Vault\n(token.dpapi / Machine Scope)"]
        ClientKey["Public Keys Only\n(Primary + Tenant Escrow)"]
        
        SQL -->|Native Dump| CoreEngine
        CoreEngine -->|Deflate L9| ZipArchive[".zip"]
        ZipArchive -->|AES-256-GCM + Dual RSA-4096| DBK2[".dbk2 Container"]
        DPAPI -.->|Mutual Auth| CoreEngine
        ClientKey -.->|Encrypt Only| CoreEngine
    end

    subgraph GoogleCloud [Zero-Trust Cloud Broker & Storage]
        Broker["Google Apps Script Broker\n(Code.gs)"]
        Drive["Customer Google Drive Folder\n(Canonical Folder Enforcement)"]
        Sheets["Master Telemetry Sheet\n(Multi-Tab Audit Logs)"]
        Sentinel["Missed-Backup Sentinel\n(Hourly SLA Monitor)"]
        
        CoreEngine -->|1. Authenticate Machine| Broker
        Broker -->|2. Issue Resumable Upload URI| CoreEngine
        CoreEngine -->|3. Stream Encrypted Chunks| Drive
        Broker -->|4. Log Execution Telemetry| Sheets
        Sentinel -->|5. Overdue SLA Alert (>26h)| AdminAlert["dulnindu@spillabs.com"]
    end

    subgraph AdminAirGap [Air-Gapped Disaster Recovery]
        AdminTool["Admin Decryption Tool\n(decrypt_gui.py / decrypt_backup.py)"]
        PrivKeys["Private Keys Offline\n(Never Deployed to Clients)"]
        Drive -.->|Download .dbk2| AdminTool
        PrivKeys -->|Decrypt .dbk2| AdminTool
        AdminTool -->|Restored .bak| TargetSQL[("Restored SQL Server")]
    end
```

---

## 🔄 Multi-Generational Compatibility Engine

Version 5.0.0 provides complete, zero-downtime backward compatibility for all prior releases (v1.x, v2.x, v3.x, and v4.0–v4.3):

* **Atomic In-Place Upgrades (`Update_App.bat`)**: Safely preserves customer databases, schedules, and server names. Auto-migrates legacy v4.0 `broker_token.dat` into Windows DPAPI `token.dpapi`.
* **Legacy OAuth Purge**: Automatically removes obsolete Google OAuth tokens (`credentials.json`, `token.json`, `client_secret.json`) from v1–v3 deployments.
* **Scheduled Task Unification**: Purges all historical task names (`DatabaseBackup_AutomatedTask`, `DatabaseBackup_Daily`, etc.) and registers the unified `Database Cloud Backup` task running under `NT AUTHORITY\SYSTEM`.
* **Universal Magic Byte Sniffer**:
  * `b"DBK2"`: Authenticates and decrypts dual-envelope (v5.0) and single-envelope (v4.0–v4.3) zero-trust archives.
  * `b"PK\x03\x04"`: Automatically recognizes unencrypted standard `.zip` archives and unpacks them without requiring keys.
  * Native SQL Header: Directly restores `.bak` files into SQL Server with exclusive `SINGLE_USER` connection locking.

---

## 💻 Operating System & Database Matrix

| Environment | Supported Versions | Recommended Deployment Pathway |
| :--- | :--- | :--- |
| **Modern Windows** | Windows Server 2025, 2022, 2019, 2016<br>Windows 11, Windows 10 (64-bit) | **Track 1: Graphical Setup Wizard** (`Setup_DatabaseBackup.exe`) |
| **Legacy Windows** | Windows Server 2012, 2012 R2<br>Windows 8.1 | **Track 1** (with KB2999226) or **Track 2** (`shell_client/`) |
| **Vintage Windows** | Windows Server 2008 R2 SP1<br>Windows 7 SP1 | **Track 2: Pure PowerShell Shell Agent** (`shell_client/`)<br>*(Zero Python dependency; runs on native .NET 4.5+ assemblies)* |
| **32-Bit (x86)** | Windows 32-bit platforms | **Track 2: Pure PowerShell Shell Agent** (`shell_client/`) |
| **Microsoft SQL Server** | SQL Server 2022, 2019, 2017, 2016, 2014, 2012, 2008 R2, 2008, 2005, 2000 | Dynamic CLI chain: ODBC Driver 18 (with TLS `-C` negotiation) down to legacy `osql.exe` |

---

## 🚀 Quick Start Deployment

### 1. Graphical Installation (Recommended for Windows Servers & PCs)
1. Extract the customer distribution package (e.g., `Client_Installation_Package_v5.0.zip`).
2. Right-click **`Setup_DatabaseBackup.exe`** and select **Run as administrator**.
3. Verify the green **Authentic Ed25519 Signed Package** banner.
4. Click **Install Now**.
5. Launch `DatabaseBackupApp.exe`, verify databases under **Databases & Schedule**, and click **⚡ RUN CLOUD BACKUP NOW**.

### 2. Headless PowerShell Deployment (For Legacy OS & Server Core)
```powershell
# Open elevated PowerShell prompt (Run as Administrator)
Set-ExecutionPolicy Bypass -Scope Process -Force
cd "Client_Installation_Package_v5.0\shell_client"
.\install_agent.ps1
```

### 3. In-Place Upgrades of Older Deployments
To upgrade an existing installation in under 60 seconds:
1. Extract the v5.0 package on the target machine.
2. Right-click **`Update_App.bat`** and select **Run as administrator**.
3. Binaries, tokens, schedules, and configurations upgrade automatically with zero data loss.

---

## 📚 Definitive Documentation Suite

All system documentation is synchronized across Microsoft Word (`.docx`) and Adobe PDF (`.pdf`):

* **[Definitive Master System Specification & Manual (v5.0.0)](ENTERPRISE_DATABASE_BACKUP_V5_MASTER_SPECIFICATION_AND_MANUAL.docx)** *(1.25 MB Word)* · **[PDF Edition](ENTERPRISE_DATABASE_BACKUP_V5_MASTER_SPECIFICATION_AND_MANUAL.pdf)** *(5.21 MB PDF)*  
  *18 comprehensive chapters covering complete architecture, cryptographic framing, cloud broker protocols, operations, and recovery drills.*
* **[Executive Technical Report & Senior Upgrade Summary](EXECUTIVE_TECHNICAL_REPORT_V5_COMPREHENSIVE_UPGRADES.docx)** *(Word)* · **[PDF Edition](EXECUTIVE_TECHNICAL_REPORT_V5_COMPREHENSIVE_UPGRADES.pdf)**  
  *Detailed technical report prepared for senior leadership and security audit committees.*
* **[Client Field Installation & Operations Guide (v5.0.0)](docs/INSTALLATION_GUIDE_v5.0.docx)** *(Word)* · **[PDF Edition](docs/INSTALLATION_GUIDE_v5.0.pdf)**  
  *Step-by-step customer onboarding and installation guide with illustrated screenshots.*
* **[Administrator Master Operations Manual](docs/ADMIN_INSTALLATION_AND_OPERATIONS_GUIDE.docx)** *(Word)* · **[PDF Edition](docs/ADMIN_INSTALLATION_AND_OPERATIONS_GUIDE.pdf)**  
  *Full IT administrator manual for provisioning, key management, and disaster recovery.*
* **[Complete System Walkthrough](docs/ENTERPRISE_DATABASE_CLOUD_BACKUP_V5_COMPLETE_SYSTEM_WALKTHROUGH.docx)** *(Word)* · **[PDF Edition](docs/ENTERPRISE_DATABASE_CLOUD_BACKUP_V5_COMPLETE_SYSTEM_WALKTHROUGH.pdf)**  
  *Architectural specification and deep dive into broker mechanics, DPAPI vaulting, and maintenance modules.*

---

## 🔒 Security & Compliance Standards
* **Data in Transit:** TLS 1.2+ mandatory over outbound HTTPS (Port 443).
* **Data at Rest:** AES-256-GCM authenticated streaming encryption with 128-bit MAC per-chunk verification.
* **Key Management:** Asymmetric RSA-4096 envelope encryption; private keys held strictly offline on air-gapped administrative media.
* **Credentials:** Sealed using Windows DPAPI bound to the local machine context (`CRYPTPROTECT_LOCAL_MACHINE`). Zero client passwords stored in plaintext.
* **Audit & Telemetry:** Multi-tab centralized audit logging in Google Sheets with hourly SLA Missed-Backup Sentinel monitoring.

---
*Enterprise Database Cloud Backup Automation v5.0.0 · Database Infrastructure & Security Engineering*
