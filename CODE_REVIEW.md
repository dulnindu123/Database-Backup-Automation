# 🔍 Senior Engineer Code Review Guide
### Enterprise Database Cloud Backup Automation · v4.2.0

Welcome! This document is designed to guide a senior software engineer, security architect, or technical lead through reviewing the codebase. It details the **threat model**, **architectural invariants**, **core engineering trade-offs**, and **step-by-step verification commands**.

---

## 1. Executive Summary & Problem Statement

In small-to-medium enterprise and retail POS environments, backing up critical databases (Microsoft SQL Server, MySQL, PostgreSQL) directly to cloud storage introduces major security vulnerabilities:
1. **Credential Exposure**: Storing Google Cloud / AWS IAM service account keys or OAuth tokens on edge Windows servers allows an attacker with local admin access to steal credentials, list/delete all company backups, or pivot into cloud infrastructure.
2. **Ransomware Deletion**: Ransomware on the client machine can wipe remote cloud backups if the client possesses delete permissions.
3. **Plaintext Leaks**: Backups left unencrypted on local disks or uploaded without client-side encryption expose sensitive customer PII and financial records.

### The Solution: Zero-Trust Client + Stateless Serverless Broker
- **Zero Cloud Credentials on Client**: The client application holds **no** Google OAuth tokens, service accounts, or API keys.
- **Client-Side Hybrid Envelope Encryption**: Every backup is compressed and encrypted into a streaming `.dbk2` archive using authenticated **AES-256-GCM** before touching the network. The ephemeral AES key is dual-wrapped with **RSA-4096** for Customer Primary and MSP Admin Escrow. All RSA private keys remain strictly **air-gapped offline**.
- **Stateless Serverless Upload Broker**: A Google Apps Script web app (`apps_script_broker/Code.gs`) acts as an authorization gatekeeper. It verifies single-use machine tokens sealed in **Windows DPAPI** and generates direct Google Drive resumable upload URIs. The client can **only** stream ciphertext into its designated folder; it cannot list, read, or delete files.

---

## 2. Core Architectural & Security Invariants

When reviewing the implementation, observe these key design guarantees:

| Invariant | Mechanism | Implementation Reference |
|---|---|---|
| **Zero Client Cloud Credentials** | Client communicates exclusively with the Apps Script broker via HTTPS JSON payloads. | [`broker_client.py`](broker_client.py) |
| **Air-Gapped Private Keys** | Only public keys (`backup_public.pem`, `escrow_public.pem`) are distributed. Private keys are generated offline and never touch client disk or cloud. | [`Tools/setup_new_customer.py`](Tools/setup_new_customer.py), [`crypto_stream.py`](crypto_stream.py) |
| **Authenticated Streaming Encryption** | 64 KiB chunked AES-256-GCM with 128-bit MAC tag. Tampering or truncation is detected immediately. Dual RSA-OAEP (SHA-256) key wrapping. | [`crypto_stream.py`](crypto_stream.py) |
| **Machine-Bound Token Storage** | Machine token `<pc_id>.<secret>` is encrypted using Windows Data Protection API (`CryptProtectData`) with `CRYPTPROTECT_UI_FORBIDDEN`. Unreadable if copied to another machine or user context. | [`broker_client.py`](broker_client.py), [`tests/test_dpapi_interop.py`](tests/test_dpapi_interop.py) |
| **Tamper-Evident Deployment** | Customer deployment `bundle.json` is signed with an administrative Ed25519 key. Installer aborts immediately if signature validation fails. | [`admin/sign_bundle.py`](admin/sign_bundle.py), [`installer_gui.py`](installer_gui.py) |
| **Apps Script 302 Redirection Handling** | Google Apps Script `ContentService` redirects POST responses with 302 to `script.googleusercontent.com/macros/echo`. Broker client automatically follows with HTTP GET to prevent HTTP 405 Method Not Allowed. | [`broker_client.py:post_broker()`](broker_client.py) |
| **Atomic Quota & Re-Enrollment** | Apps Script broker uses Google `LockService` for concurrency control. Limits uploads to 3 per PC/day. If a machine is re-imaged, it updates the registered token hash in-place to prevent machine bricking. | [`apps_script_broker/Code.gs`](apps_script_broker/Code.gs) |
| **Strict Subprocess Path Quoting** | Windows Task Scheduler registrations quote binary paths with spaces (`schtasks.exe /tr "\"C:\Program Files\...\" --auto"`) preventing command-line argument injection. | [`installer_gui.py`](installer_gui.py) |

---

## 3. Tour of the Codebase

### Core Client Engine
- **[`backup_core.py`](backup_core.py)**: Backup lifecycle coordinator. Manages native database dumps (`sqlcmd`, `mysqldump`, `pg_dump`), drives streaming encryption, monitors local storage, and streams chunked HTTP PUT requests to Google Drive resumable upload sessions with `Content-Range` headers.
- **[`crypto_stream.py`](crypto_stream.py)**: Low-level cryptographic streaming engine. Implements the `.dbk2` binary container format (version `0x01`, dual RSA-4096 envelope headers, AES-256-GCM chunked pipeline).
- **[`broker_client.py`](broker_client.py)**: HTTP broker client. Manages hardware fingerprint generation (`SHA-256` of Motherboard UUID + CPU ID + MAC), DPAPI token encryption/decryption, Apps Script 302 redirect resolution, and retry policies.
- **[`preflight.py`](preflight.py)**: 8-point pre-flight diagnostics module. Verifies broker health, token validity, RSA key validity (bits ≥ 3072, key distinctness), SQL Server connectivity, disk space sufficiency, cloud-sync folder conflict detection (blocks running inside OneDrive/Dropbox), and ACL permissions.
- **[`auto_backup.py`](auto_backup.py)**: Headless CLI entrypoint invoked by the Windows Task Scheduler.
- **[`app_gui.py`](app_gui.py)**: Modern desktop management GUI built with Tkinter/CustomTkinter.

### Setup & Onboarding Pipeline
- **[`installer_gui.py`](installer_gui.py)**: Zero-typing installation wizard compiled with PyInstaller (`uac_admin=True`). Verifies Ed25519 signed `bundle.json`, executes pre-flight diagnostics, enrolls machine with broker, seals token into DPAPI, and configures Windows Scheduled Tasks.
- **[`Tools/setup_new_customer.py`](Tools/setup_new_customer.py)**: Interactive admin CLI for onboarding a single customer. Generates RSA keypairs, signs deployment bundle, and provisions ready-to-deploy customer zip.
- **[`Tools/batch_setup_customers.py`](Tools/batch_setup_customers.py)**: Bulk onboarding engine for multi-tenant deployment. Processes batch customer slugs, generates isolated keypairs, writes `enroll_codes_for_sheet.tsv`, and generates customer packages.
- **[`Tools/decrypt_backup.py`](Tools/decrypt_backup.py)**: Disaster recovery CLI. Authenticates GCM tag and decrypts `.dbk2` archive using air-gapped RSA private key.

### Cloud Broker (Zero-Billing)
- **[`apps_script_broker/Code.gs`](apps_script_broker/Code.gs)**: Serverless upload broker deployed as a Google Apps Script Web App. Manages enrollment, token authentication, upload session generation via Google Drive API, daily rate limiting, and structured telemetry logging to Google Sheets.
- **[`apps_script_broker/pull_backup.py`](apps_script_broker/pull_backup.py)**: Administrative read-only Google Drive retrieval script for air-gapped recovery operations.

### Build & Release Verification
- **[`audit_build.py`](audit_build.py)**: Zero-trust build auditor. Enforces strict file allowlists, scans `dist/` for private keys (`*_private.pem`) or leaked tokens, and validates master template empty fields.
- **[`release.py`](release.py)**: Production release pipeline. Compiles binaries via PyInstaller, runs security audits, synchronizes assets to `Client_Installation_Package`, and computes/verifies SHA-256 manifests across all files.

---

## 4. Test Suite & Verification Instructions

The codebase includes an extensive automated test suite covering unit tests, cryptographic roundtrips, broker protocol simulations, DPAPI interop, error code contracts, and end-to-end integration flows.

### Running the Full Test Suite
To run all 73 automated tests:
```powershell
python -m unittest discover tests
```
*Expected Result:*
```text
Ran 73 tests in ~14s — OK (0 failures, 0 errors)
```

### Key Test Suites to Inspect:
1. **[`tests/test_full_e2e_flow.py`](tests/test_full_e2e_flow.py)**: Full end-to-end lifecycle using a mock lightweight HTTP server (`dev_broker.py`):
   - Health probe ping
   - Machine token verification
   - Hardware fingerprint generation
   - Database backup simulation
   - Streaming AES-256-GCM + dual RSA-4096 encryption
   - Resumable chunked upload with `Content-Range` headers
   - Decryption and SHA-256 plaintext integrity validation
2. **[`tests/test_failure_matrix.py`](tests/test_failure_matrix.py)**: Validates that failure modes produce deterministic error codes (`ERR_NOT_APPS_SCRIPT`, `ERR_HEALTH_EXCEPTION`, `ERR_TOKEN_FILE_ABSENT`, `ERR_DPAPI_EMPTY`, `ERR_PRIMARY_KEY_TOO_SHORT`, `ERR_KEYS_NOT_DISTINCT`, `ERR_SQL_CONN_FAILED`, `ERR_CLOUD_SYNC_DETECTED`, `ERR_ACL_DENIED`).
3. **[`tests/test_dpapi_interop.py`](tests/test_dpapi_interop.py)**: Validates Windows DPAPI encryption, machine context boundaries, and UI suppression flags.
4. **[`tests/test_stray_files_and_allowlist.py`](tests/test_stray_files_and_allowlist.py)**: Validates zero stray configuration files and empty master templates.
5. **[`tests/test_log_scan.py`](tests/test_log_scan.py)**: Scans source files and logs to ensure tokens (`pc-*.secret`) are masked and never printed or persisted in plaintext.

### Running the Zero-Trust Package Audit:
```powershell
python audit_build.py
```
*Expected Result:*
```text
[OK] Package Allowlist Audit: All files match strict explicit allowlist.
[OK] Master Config Audit: BROKER_URL, Drive ID, and Sheet ID are strictly empty.
[OK] Secret Guard Audit: 0 private keys or secret files detected.
```

### Verifying the SHA-256 Release Manifest:
```powershell
python release.py --skip-compile
```
*Expected Result:*
```text
[OK] 100% Verified: All 871 files match SHA-256 manifest checksums!
```

---

## 5. Security & Threat Model Checklist

| Threat | System Defense | Validation Test |
|---|---|---|
| **Ransomware wiping backups** | Client only receives a single-use resumable upload URI from the broker. No list, delete, or overwrite permissions exist on client. | [`tests/test_broker_client.py`](tests/test_broker_client.py) |
| **Token theft across machines** | Token is sealed with Windows DPAPI machine/user context (`CryptProtectData`). Cannot be decrypted on another machine. | [`tests/test_dpapi_interop.py`](tests/test_dpapi_interop.py) |
| **Rogue installer modification** | `bundle.json` is signed with Ed25519. Tampering causes immediate signature verification failure. | [`tests/test_customer_onboarding.py`](tests/test_customer_onboarding.py) |
| **Cloud account takeover** | Backups are stored as encrypted `.dbk2` binary ciphertext. Google or attackers with Drive access cannot decrypt data without offline RSA private keys. | [`tests/test_crypto.py`](tests/test_crypto.py) |
| **Token leakage in logs** | `emit_log` automatically applies regex redaction replacing tokens with `[SEALED_SECRET]`. | [`tests/test_log_scan.py`](tests/test_log_scan.py) |
| **Replay / Brute force** | Single-use enrollment codes, HMAC-SHA256 token verification, daily quota enforcement via `LockService`. | [`apps_script_broker/Code.gs`](apps_script_broker/Code.gs) |

---

## 6. Feedback & Inquiries
For questions regarding the architecture, implementation specifics, or deployment patterns, feel free to open a review thread or contact the project author.
