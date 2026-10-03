# System Architecture & Code Guide

## Overview
This system is an automated, zero-trust backup architecture designed to securely upload encrypted database backups to Google Drive using Google Apps Script as a Zero-Billing Upload Broker.

## Components

### 1. Client-Side Backup Application (`DatabaseBackupApp`)
Runs on the customer's machine. It performs the following:
- Compresses the target database directory.
- Encrypts the archive using ChaCha20-Poly1305 (via `.dbk2` format).
- Enrolls with the Apps Script Broker using an `enroll_code` to receive a time-staggered upload offset.
- Requests a resumable upload URI from the Apps Script Broker.
- Uploads the encrypted archive directly to Google Drive in 8MB chunks using the `Content-Range` header.
- Assesses local disk telemetry and reports it to the Broker.

**Key Files:**
- `backup_core.py`: Core backup compression, encryption, and chunked HTTP uploading logic.
- `broker_client.py`: HTTP client wrapper for communicating with the Apps Script Broker (handling JSON POSTs and 302 redirects).
- `auto_backup.py`: The scheduled task entrypoint.
- `crypto_stream.py`: Streaming encryption implementation.
- `installer_gui.py`: The PyInstaller-built wizard that securely installs the application and handles one-time enrollment.

### 2. Google Apps Script Broker (`apps_script_broker/Code.gs`)
A lightweight, free, serverless API hosted on Google Apps Script. It acts as the gatekeeper to Google Drive, ensuring customers can only upload files (and cannot list, download, or delete them).

**Key Features:**
- **doPost(e)**: Receives JSON payloads from the client for actions: `enroll`, `verify`, `request_upload`, and `report_status`.
- **Atomic Enrollment**: Uses `LockService` to ensure a PC can only enroll once. Validates against `ENROLL_CODE` stored in a hidden Google Sheet.
- **Quota Management**: Limits each PC to 3 uploads per day, verified by scanning the `Audit` sheet.
- **Resumable Sessions**: Uses `UrlFetchApp` to call the Drive API (`uploadType=resumable`) and returns the session URI back to the client.

### 3. Read-Only Restore Script (`apps_script_broker/pull_backup.py`)
Since the Broker and Client hold no read credentials (Zero-Trust), restores must be performed on an air-gapped administrative machine.
- Uses a Service Account with the `https://www.googleapis.com/auth/drive.readonly` scope.
- Pulls `.dbk2` files down from the central Google Drive.

## Security Posture
- **Zero-Billing**: No Google Cloud Billing account is required.
- **Ransomware Vulnerability**: Unlike Google Cloud Storage WORM, Google Drive does not support Object Retention Locks. If the primary Google Workspace account running the Apps Script is compromised, an attacker can empty the trash and delete backups.
- **Encryption**: Files are encrypted client-side using a public key. The private key never touches the customer's machine or the Google Drive.

## Deployment
1. Import `apps_script_broker/Code.gs` into a new Apps Script project.
2. Link the Apps Script to a Google Sheet with tabs: `Config`, `Tokens`, `Audit`, `Telemetry`.
3. Deploy as Web App -> Execute as: Me -> Access: Anyone.
4. Run `rebuild_client_installation_package.py` locally to bake the Broker URL into the Windows installer.
