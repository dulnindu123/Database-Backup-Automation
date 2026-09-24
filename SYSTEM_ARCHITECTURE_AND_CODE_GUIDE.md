# 📘 Comprehensive System Architecture & Deep Code Guide
## Enterprise Database Cloud Backup Automation System

**Author / Developer:** Dulnindu Saranga  
**System Target:** Microsoft SQL Server, Google Cloud Platform (Drive API v3, Sheets API v4), Windows 10/11 / Windows Server  
**Architecture Pattern:** Decoupled Model-View-Controller (MVC) / Stateless Core Engine with Asynchronous GUI Presentation  

---

## 📑 Table of Contents

1. [System Component Inventory & File Map](#1-system-component-inventory--file-map)
2. [End-to-End Architectural Decomposition](#2-end-to-end-architectural-decomposition)
3. [The Complete Step-by-Step Data Flow](#3-the-complete-step-by-step-data-flow)
4. [Deep Code Inspection & Function Breakdown](#4-deep-code-inspection--function-breakdown)
   - [4.1 `auto_backup.py` — The Master Traffic Router](#41-auto_backuppy--the-master-traffic-router)
   - [4.2 `backup_core.py` — The Stateless Execution Engine](#42-backup_corepy--the-stateless-execution-engine)
   - [4.3 `app_gui.py` — The Asynchronous Desktop Interface](#43-app_guipy--the-asynchronous-desktop-interface)
   - [4.4 `installer_gui.py` — The Standalone Setup Wizard](#44-installer_guipy--the-standalone-setup-wizard)
   - [4.5 Configuration & Credentials Schema](#45-configuration--credentials-schema)
5. [Threading, Concurrency & UI Responsiveness](#5-threading-concurrency--ui-responsiveness)
6. [Enterprise Security & Credential Architecture](#6-enterprise-security--credential-architecture)
7. [Zero Local Storage Footprint (Two-Phase Purge)](#7-zero-local-storage-footprint-two-phase-purge)
8. [Unattended Windows System Service & Session 0 Architecture](#8-unattended-windows-system-service--session-0-architecture)
9. [Thread-Safe Emergency Stop & Cancellation Architecture](#9-thread-safe-emergency-stop--cancellation-architecture)
10. [SQL Server Error 5 & Msg 3201 Auto-Failover Engine](#10-sql-server-error-5--msg-3201-auto-failover-engine)
11. [Enterprise Clean Uninstallation Architecture & Self-Migrating Batch Pattern](#11-enterprise-clean-uninstallation-architecture--self-migrating-batch-pattern)
12. [Senior Engineering Review & Defense Cheat Sheet](#12-senior-engineering-review--defense-cheat-sheet)

---

## 1. System Component Inventory & File Map

In the primary code repository (`BackupAutomation/`), the system consists of foundational source files, supporting configuration templates, build tooling, and uninstallation automation:

```text
BackupAutomation/
│
├── auto_backup.py             # Dual-mode execution router (GUI on double-click, headless on --auto / --daemon)
├── backup_core.py             # Pure, stateless core engine (SQL failover, Level 9 Zip, Drive/Sheets API, Services)
├── app_gui.py                 # Windows 11 desktop GUI built with CustomTkinter & Service Controls
├── installer_gui.py           # Autonomous installer wizard with uninstaller generator & registry registration
├── Uninstall.bat              # Self-migrating clean uninstaller (process kill, task purge, folder wipe)
│
├── config.json                # Runtime configuration (SQL instance, database list, Drive/Sheet IDs)
├── client_secret.json         # Google Cloud Platform OAuth 2.0 Client credentials
├── credentials.json           # User authorization cache with persistent offline refresh token
│
├── create_icon.py             # Script generating multi-resolution application icons
├── app_icon.ico               # Windows application icon (16x16 to 256x256)
├── app_icon.png               # High-resolution PNG branding asset
│
├── build_executable.bat       # Production PyInstaller compilation pipeline with auto-scratch purge
├── DatabaseBackupApp.spec     # PyInstaller spec definition with bundled assets and dependencies
├── Setup_DatabaseBackup.spec  # PyInstaller spec definition for standalone installer wizard
└── requirements.txt           # Pinned Python package dependencies
```

---

## 2. End-to-End Architectural Decomposition

```
                               ┌─────────────────────────────┐
                               │       Execution Trigger     │
                               │  (User Click or Scheduler)  │
                               └──────────────┬──────────────┘
                                              │
                                              ▼
                               ┌─────────────────────────────┐
                               │       auto_backup.py        │
                               │   (Dual-Mode CLI Router)    │
                               └───────┬─────────────┬───────┘
                                       │             │
                No CLI Arguments       │             │   CLI Flag: '--auto'
             (Interactive User Mode)   │             │   (Automated Background)
                                       ▼             ▼
                     ┌────────────────────┐   ┌───────────────────────────┐
                     │     app_gui.py     │   │   Headless Silent Mode    │
                     │ (CustomTkinter UI) │   │ (No UI, Direct Log Stream)│
                     └─────────┬──────────┘   └─────────────┬─────────────┘
                               │                            │
                               └──────────────┬─────────────┘
                                              │
                                              ▼
                               ┌─────────────────────────────┐
                               │       backup_core.py        │
                               │   (Pure Stateless Engine)   │
                               └───────┬──────┬──────┬───────┘
                                       │      │      │
                ┌──────────────────────┘      │      └──────────────────────┐
                ▼                             ▼                             ▼
   ┌─────────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────────┐
   │   Microsoft SQL Server  │   │     Compression Layer   │   │   Google Cloud Platform │
   │   - sqlcmd subprocess   │   │   - Level 9 Deflate     │   │   - Drive API v3        │
   │   - Windows Auth (-E)   │   │   - Byte verification   │   │   - Sheets API v4       │
   │   - ODBC 18 Trust (-C)  │   │   - Phase 1 Purge (.bak)│   │   - Phase 2 Purge (.zip)│
   └─────────────────────────┘   └─────────────────────────┘   └─────────────────────────┘
```

### Key Architectural Tenet: Headless Engine Decoupling
* **`backup_core.py` has zero dependencies on UI packages.** It imports neither `tkinter` nor `customtkinter`.
* Every function accepts optional logging and progress callback hooks (`log_cb`, `progress_cb`, `status_cb`).
* This enables the exact same engine to run in:
  1. An interactive desktop application with real-time progress bars.
  2. A completely silent Windows Task Scheduler task running at 02:00 AM with zero popups.
  3. A headless CI/CD pipeline or CLI script.

---

## 3. The Complete Step-by-Step Data Flow

When a backup execution cycle initiates, the system executes seven sequential, fault-tolerant stages:

```
[1. Trigger] ➔ [2. OAuth Check] ➔ [3. SQL Dump] ➔ [4. Deflate L9] ➔ [5. Drive Upload] ➔ [6. Sheets Telemetry] ➔ [7. Local Purge]
```

### Stage 1: Trigger & Day-of-Week Validation
* **Interactive Mode:** User clicks `"🚀 Start Full Backup Now"` in the desktop GUI.
* **Automated Mode:** Windows Task Scheduler invokes `DatabaseBackupApp.exe --auto` at 02:00 AM on Mondays.
* **Validation:** If `STRICTLY_MONDAYS_ONLY` is enabled, the code evaluates `datetime.now().weekday() == 0`. Non-Monday executions terminate immediately with a clean log entry: `Today is <Day>, skipping backup.`

### Stage 2: Google Authentication Check
* Before initiating resource-heavy database actions, the engine validates the Google Cloud session via `authenticate()`.
* It verifies `credentials.json` on disk:
  - If valid: Uses existing token.
  - If expired: Silently invokes Google's token refresh endpoint using the offline `refresh_token`.
  - If missing: Spawns an ephemeral local web server (`InstalledAppFlow`) to complete the OAuth 2.0 browser handshake.

### Stage 3: Microsoft SQL Server Extraction
* Native database extraction executes via `perform_sql_backup()`.
* Invokes `sqlcmd` through an isolated Python subprocess:
  ```cmd
  sqlcmd -S "localhost\SQL25SARANGA" -E -C -Q "BACKUP DATABASE [RGT] TO DISK='C:\temp\backups\RGT_20260922.bak' WITH FORMAT"
  ```
  - **`-E` (Trusted Connection):** Uses current Windows user context, eliminating plaintext database passwords.
  - **`-C` (Trust Server Certificate):** Circumvents strict TLS certificate chain validation introduced in Microsoft ODBC Driver 18, allowing seamless operation with local self-signed certificates.
* **Output:** A raw `.bak` file in the configured `BACKUP_FOLDER` (e.g. 455.40 MB).

### Stage 4: Maximum Deflation Compression
* Raw SQL Server backups contain sparse, uncompressed database pages.
* The engine passes the `.bak` file into Python's native `zipfile` module:
  ```python
  zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9)
  ```
* **Phase 1 Storage Cleanup:** The moment the `.zip` archive is successfully verified on disk, the raw `.bak` file is immediately deleted via `os.remove(bak_filepath)`.
* **Output:** 455.40 MB raw backup compresses to **80.95 MB** (~82.2% reduction).

### Stage 5: Resumable Google Drive Upload
* The compressed archive is streamed to Google Drive API v3 via `MediaFileUpload(..., resumable=True)`.
* Uploads are chunked (5 MB buffers) and wrapped in an exponential retry loop (up to 3 retries).
* Once uploaded, the engine extracts the file's Google Drive unique `id` and resolves the viewable URL:
  `https://drive.google.com/file/d/{file_id}/view?usp=sharing`

### Stage 6: Centralized Compliance Telemetry (Google Sheets)
* Connects to Google Sheets API v4 using `gspread`.
* Verifies or dynamically inserts the compliance header:
  `[ "Date & Time", "Backup File Name", "Backup File Size", "Google Drive Download Link" ]`
* Appends an immutable audit record:
  ```text
  ["2026-09-22 17:42:01", "RGT_20260922_174201.zip", "80.95 MB", "https://drive.google.com/file/d/1gQ.../view"]
  ```

### Stage 7: Zero Local Storage Footprint (Phase 2 Cleanup)
* Now that the archive is confirmed stored in Google Drive and logged in Google Sheets:
  ```python
  if config.get("DELETE_LOCAL_AFTER_UPLOAD", True):
      os.remove(backup_zip)
  ```
* The local `.zip` file is deleted from the storage drive (`C:\temp\backups`).
* **Result:** Local persistent disk consumption drops to **zero bytes**, preventing on-premise disk exhaustion permanently.

---

## 4. Deep Code Inspection & Function Breakdown

---

### 4.1 `auto_backup.py` — The Master Traffic Router

`auto_backup.py` acts as the single point of entry for the compiled binary.

```python
def main():
    if "--auto" in sys.argv or "-a" in sys.argv:
        # Scheduled Execution Route
        run_automated_mode()
    else:
        # Interactive Desktop Route
        from app_gui import DatabaseBackupApp
        app = DatabaseBackupApp()
        app.mainloop()
```

* **Purpose:** Enables a single `.exe` to serve two completely different operational modes without requiring separate build targets.
* **`run_automated_mode()`:** Checks Monday constraints, executes `run_full_backup()`, redirects output to `backup_log.txt`, and exits with standard OS exit codes (0 for success, 1 for failure).

---

### 4.2 `backup_core.py` — The Stateless Execution Engine

This module contains the entire operational logic of the system:

#### 1. Configuration Management (`load_config`, `save_config`)
* Reads `config.json` relative to the running script or frozen PyInstaller `sys._MEIPASS` directory.
* If missing, populates and persists an enterprise-safe `default_config` containing fallback instances, default schedules, and enabled cleanup flags.

#### 2. Authentication Lifecycle (`authenticate`, `reset_credentials`)
* Manages Google OAuth 2.0 credentials (`client_secret.json` ➔ `credentials.json`).
* Implements silent token refresh via `creds.refresh(Request())`.
* Configures `os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'` to prevent runtime exceptions caused by Google OAuth scope normalization.
* `reset_credentials()` safely unlinks `credentials.json` to allow clean account switching.

#### 3. Diagnostic Health Checks (`test_google_connection`)
* Performs non-destructive read validation against Google Drive (fetching folder metadata by ID) and Google Sheets (validating title and worksheet dimensions), returning a structured health dictionary:
  `{"drive": bool, "sheet": bool, "drive_name": str, "sheet_title": str, "error": str}`.

#### 4. SQL Extraction & Deflation (`generate_and_compress_backup`)
* Constructs the native `sqlcmd` command line with `-E` (Windows Auth) or `-U`/`-P` (SQL Auth).
* Injects `-C` to guarantee TLS certificate bypass for local SQL Server 2022 / ODBC 18 instances.
* Executes Level 9 Deflate compression via Python's native `zipfile` library.
* Enforces Phase 1 cleanup by deleting the raw `.bak` file upon successful compression.

#### 5. Cloud Transport (`upload_to_google_drive`, `update_google_sheet`)
* `upload_to_google_drive`: Streams data in 5 MB resumable chunks with up to 3 automatic retry attempts spaced 10 seconds apart. Sets public view permissions and synthesizes canonical links.
* `format_file_size`: Formats byte counts into precision human-readable units (`B`, `KB`, `MB`, `GB`).
* `update_google_sheet`: Appends execution audit records into Google Sheets with timestamp, file name, formatted size, and URL.

#### 6. Master Orchestration (`run_full_backup`)
* Iterates through `TARGET_DATABASES`.
* Coordinates: SQL Backup ➔ Level 9 Zip ➔ Drive Upload ➔ Sheets Audit.
* Enforces Phase 2 cleanup: deletes the `.zip` archive from the storage drive upon successful sync.
* Preserves the local file and logs an alert if cloud upload fails, ensuring zero data loss.

#### 7. Local Storage Maintenance (`cleanup_local_backup_folder`)
* Sweeps the backup folder (`C:\temp\backups`) and removes any orphaned `.bak` or `.zip` files from failed or interrupted executions.
* Returns the count of deleted files and the exact amount of disk space freed.

#### 8. Auto-Discovery & System Queries (`detect_sql_server_instances`, `detect_user_databases`)
* `detect_sql_server_instances`: Inspects the Windows Registry at:
  `HKLM\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL`
  to automatically find named instances (e.g. `SQL25SARANGA`, `SQLEXPRESS`). Falls back to querying the Windows Service Control Manager for `MSSQL$*` services.
* `detect_user_databases`: Connects via `sqlcmd` and queries:
  ```sql
  SELECT name FROM sys.databases WHERE database_id > 4 AND state_desc = 'ONLINE';
  ```
  filtering out system databases (`master`, `tempdb`, `model`, `msdb`) to auto-populate customer databases.

#### 9. Task Scheduler Automation (`get_scheduler_status`, `enable_scheduler`, `disable_scheduler`)
* Interfaces directly with `schtasks.exe`.
* `get_scheduler_status`: Parses CSV output (`schtasks /query /tn DatabaseBackupAutomation_Weekly /fo CSV /nh`) to extract active status and next run datetime.
* `enable_scheduler`: Registers the weekly Monday task at the configured time under the current user's profile with standard privileges (`/rl LIMITED`).
* `disable_scheduler`: Deletes the task via `schtasks /delete /tn DatabaseBackupAutomation_Weekly /f`.

---

### 4.3 `app_gui.py` — The Asynchronous Desktop Interface

Constructed with `customtkinter`, featuring modern typography, dark-mode cards, real-time logging, and fluid responsiveness.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🛡️ Database Cloud Backup Automation — Enterprise Edition                         [—] [□] [✕] │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│   [ 📊 Dashboard ]     [ ⏰ Auto Schedule ]     [ ⚙️ Settings ]     [ 🩺 Diagnostics ]       │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                             │
│  ┌─────────────────────┐   ┌─────────────────────┐   ┌───────────────────────────────────┐  │
│  │ 🖥️ SQL Server       │   │ 🗄️ Target DBs       │   │ ☁️ Google Cloud Connection        │  │
│  │ localhost\SQLEXPRESS│   │ 2 Databases Config. │   │ OAuth 2.0 Ready (15 GB Storage)   │  │
│  │ Status: ● CONNECTED │   │ [ProductionDB, CRM] │   │ Status: ● AUTHENTICATED           │  │
│  └─────────────────────┘   └─────────────────────┘   └───────────────────────────────────┘  │
│                                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 🚀 [ Start Full Backup Now ]                🛑 [ STOP BACKUP (Emergency Abort) ]      │  │
│  └───────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                             │
│  Backup Progress: [████████████████████████████████████████████████░░░░░░░░░░] 78%           │
│  Current Operation: Uploading 'ProductionDB_20260924.zip' to Google Drive (2MB/s)...        │
│                                                                                             │
│  ┌─ Real-Time Diagnostics & Execution Log ────────────────────────────────────────────────┐  │
│  │ [17:06:19] [INFO] STARTING BACKUP EXECUTION CYCLE                                      │  │
│  │ [17:06:19] [INFO] Connecting to SQL Server: localhost\SQLEXPRESS...                   │  │
│  │ [17:06:22] [SUCCESS] SQL backup completed for 'ProductionDB' (455 MB).                 │  │
│  │ [17:06:25] [SUCCESS] Compressed to Level 9 Deflate: ProductionDB_20260924.zip (81 MB) │  │
│  │ [17:06:26] [INFO] Streaming archive to Google Drive Folder: 1LKuo7j4cHvvP0...          │  │
│  └────────────────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                             │
│  [ 📁 Open Backups ]    [ ☁️ Open Drive ]    [ 📊 Open Sheet ]    [ 🧹 Clean Storage (0 MB) ]│
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

<div align="center">
  <img src="./docs/images/live_logs_dashboard.png" alt="Live Execution Logs & Dashboard" width="750">
  <br>
  <em>Figure 1: Live Real-Time Execution Logs & Interactive Dashboard Interface</em>
</div>

#### Key Architectural Highlights:
* **Background Worker Threading:** Prevents Windows "Application Not Responding" locks during heavy compression or multi-hundred-megabyte network transfers.
* **Thread-Safe UI Marshaling:** Background threads communicate with Tkinter via `self.after(0, callback)`, ensuring memory safety and zero GUI deadlocks.
* **Real-Time Log Streamer:** Custom `_append_log()` captures log events with timestamps and severity badges (`[INFO]`, `[SUCCESS]`, `[WARNING]`, `[ERROR]`) into an autoscrolling text terminal.
* **Emergency Stop Button (`🛑 STOP BACKUP`):** Bound to `BackupCancellationController`, giving operators instantaneous ability to abort active SQL queries, terminate child processes, close streaming sockets, and purge partial files.

#### 4 Main Tabs:
1. **Dashboard Tab**: Displays SQL status card, database count card, Google connection card, live log viewer, `"🚀 Start Full Backup Now"` and `"🛑 STOP BACKUP"` buttons, and quick-access utility buttons (`📁 Open Backups`, `☁ Open Drive`, `📊 Open Sheet`, `🧹 Clean Storage`).
2. **Schedule Tab**: Dual execution security context chooser (Standard User Task vs Unattended Windows System Service running under `NT AUTHORITY\SYSTEM` in Session 0), schedule time picker, and startup recovery trigger.
3. **Settings Tab**: Visual configuration for SQL Server name, user databases, credentials, Google Drive Folder ID, Google Sheet ID, Monday-only switch, and the `Delete local backup file after upload` toggle, plus **Application Lifecycle Management** (`🗑️ Uninstall Application`).
4. **Diagnostics Tab**: System health monitor showing Python runtime version, available ODBC drivers, Windows OS build, and cloud latency metrics.

---

### 4.4 `installer_gui.py` — The Standalone Setup Wizard

An autonomous deployment wizard packaged as `Setup_DatabaseBackup.exe` built with CustomTkinter:

<div align="center">
  <img src="./docs/images/setup_wizard.png" alt="Database Cloud Backup Setup Wizard" width="750">
  <br>
  <em>Figure 2: Autonomous Installation Wizard with Directory Customization & Service Registration</em>
</div>

#### Deployment Capabilities:
* **Configurable Target Directory:** Defaults to `%LOCALAPPDATA%\Programs\DatabaseBackupApp`, fully customizable by administrators.
* **Zero Admin Rights Required (Standard User Safe):** Installs into user programs without mandatory UAC elevation prompts, while offering automated elevation if System Service mode is requested.
* **Windows Shell Integration:** Automatically generates high-resolution desktop and Start Menu shortcuts with embedded application icons.
* **Built-in Self-Migrating Uninstaller:** Copies `Uninstall.bat` directly into the destination directory and registers the application into Windows *Installed Apps* (`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall`).
* **Source Validation & Self-Healing:** Validates installation payload files (`AppFiles/`) and provides clear diagnostic dialogs if deployment assets are moved.

---

### 4.5 Configuration & Credentials Schema

#### `config.json`
```json
{
    "SQL_SERVER_NAME": "localhost\\SQL25SARANGA",
    "SQL_USERNAME": "",
    "SQL_PASSWORD": "",
    "BACKUP_FOLDER": "C:\\temp\\backups",
    "BACKUP_EXTENSION": ".zip",
    "TARGET_DATABASES": [
        "UserDB",
        "RGT"
    ],
    "GOOGLE_DRIVE_FOLDER_ID": "1LKuo7j4cHvvP0-p0C6PVo6gdkgoVBaQ4",
    "GOOGLE_SHEET_ID": "1FAnmfTAixeDgwA5f3TvJ9IEtFp1OuFTyw3UpDiOdvwg",
    "STRICTLY_MONDAYS_ONLY": true,
    "SCHEDULE_TIME": "02:00",
    "DELETE_LOCAL_AFTER_UPLOAD": true
}
```

#### `credentials.json` (Stored OAuth Token Structure)
```json
{
    "token": "ya29.a0AfH6SM...",
    "refresh_token": "1//04hE8...",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "84883456...apps.googleusercontent.com",
    "client_secret": "GOCSPX-...",
    "scopes": [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/spreadsheets"
    ],
    "expiry": "2026-09-22T19:42:01.000Z"
}
```

---

## 5. Threading, Concurrency & UI Responsiveness

### The Problem in Desktop Automation:
SQL backups of enterprise databases (e.g. `RGT` at 455 MB) and Level 9 compression take 10 to 30 seconds of intensive disk and CPU I/O. If executed on Tkinter's main event loop thread, Windows flags the window as frozen ("Not Responding"), destroying user confidence.

### The Solution:
```python
def _start_backup_thread(self):
    self.btn_run_backup.configure(state="disabled")
    thread = threading.Thread(target=self._run_backup_worker, daemon=True)
    thread.start()

def _run_backup_worker(self):
    success, summary = run_full_backup(
        config=self.config_data,
        log_cb=self._append_log_threadsafe,
        progress_cb=self._update_progress_threadsafe,
        status_cb=self._update_status_threadsafe
    )
    self.after(0, lambda: self._on_backup_finished(success, summary))
```

* **Daemon Worker Threads:** The heavy workload runs in the background. The main thread remains 100% available to repaint pixels, handle window moves, and animate widgets.
* **Thread-Safe Callbacks:** Background threads never touch UI widgets directly. They marshal updates through `self.after(0, ...)`, ensuring compliance with Tkinter's single-threaded GUI model.

---

## 6. Enterprise Security & Credential Architecture

### 1. OAuth 2.0 PKCE Flow vs. Service Accounts
* **Why Service Accounts Fail:** Google Cloud Service Accounts have **0 bytes of personal Google Drive storage**. When uploading database dumps, Service Accounts fail with `403 storageQuotaExceeded` unless assigned enterprise domain-wide delegation on Google Workspace.
* **Our Solution:** Utilizes standard Google OAuth 2.0 user credentials (`InstalledAppFlow`). The user authenticates once via browser. The application acquires an offline `refresh_token`.
* **Silent Token Rotation:** When access tokens expire after 60 minutes, the application automatically requests a new access token from Google without user intervention.

<div align="center">
  <img src="./docs/images/google_oauth_branding.png" alt="Google Cloud Console OAuth 2.0 Configuration" width="750">
  <br>
  <em>Figure 3: Google Cloud Platform OAuth Consent Screen Configuration & API Credentials</em>
</div>

### 2. Least-Privilege Scopes
The application requests only two tightly restricted scopes:
* `https://www.googleapis.com/auth/drive.file`: Grants access **only** to files created by this application. It cannot view, read, or delete existing personal files, documents, or photos in the user's Google Drive.
* `https://www.googleapis.com/auth/spreadsheets`: Grants permission to append rows to the designated compliance audit spreadsheet.

### 3. Scope Relaxation Compatibility
Google Cloud frequently consolidates legacy OAuth scope URLs into canonical URLs. To prevent standard Python libraries from throwing `ScopeChangedError`, the engine sets:
```python
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
```

### 4. Zero Secrets in Version Control (.gitignore)
All sensitive tokens, private secrets, and database dumps are excluded from Git:
```gitignore
client_secret.json
credentials.json
*.bak
*.zip
backup_log.txt
```
The repository tracks only clean `.template.json` files, preventing accidental credential leakage.

---

## 7. Zero Local Storage Footprint (Two-Phase Purge)

To eliminate on-premise disk exhaustion on production servers:

| Phase | Event Trigger | Action Taken | Disk Impact |
| :--- | :--- | :--- | :--- |
| **Phase 1** | ZIP compression completes successfully | Raw `.bak` file is deleted via `os.remove(bak_filepath)` | Reclaims ~82% of space immediately |
| **Phase 2** | Google Drive upload completes & Google Sheets logs audit row | Compressed `.zip` file is deleted via `os.remove(zip_filepath)` | Reclaims remaining 18% (0 bytes left) |
| **Safety Net** | Google Drive upload fails or network drops | Local `.zip` file is **preserved** and logged as an error | Guarantees no data loss |
| **On-Demand** | User clicks `"🧹 Clean Storage"` in GUI | `cleanup_local_backup_folder()` purges any residual files | Reclaims disk space on demand |

---

## 8. Unattended Windows System Service & Session 0 Architecture

For production enterprise servers and Multi-User Remote Desktop (RDS/RDP) environments, the application provides an **Unattended Windows System Service Mode**.

### 8.1 Architectural Problem on Enterprise Servers
* Standard user-level scheduled tasks require an interactive user login session.
* On enterprise servers, automated maintenance restarts or power recycles leave the machine at the Windows lock screen without any logged-in administrator.
* Furthermore, RDP sessions often disconnect or sign out automatically due to inactive group policy timeouts, which abruptly kills standard desktop tasks.

### 8.2 The Solution: Session 0 Isolated System Service
The application can be registered as an unattended system service executing under `NT AUTHORITY\SYSTEM` with `/rl HIGHEST`.

```mermaid
graph TD
    A["System Boot / Windows Startup"] --> B["Session 0 Service Dispatcher"]
    B --> C["Database Cloud Backup (System Service)<br/>Runs as NT AUTHORITY\\SYSTEM"]
    C --> D{"Active User Logged In?"}
    D -->|"No (Headless Console)"| E["Executes Silently in Session 0"]
    D -->|"Yes (RDP / Console User)"| E
    E --> F["Read config.json & token.json from %LOCALAPPDATA%\\Programs"]
    F --> G["Execute SQL Backup & Failover Engine"]
    G --> H["Level 9 Deflate Compression"]
    H --> I["Google Drive Upload & Sheets Audit Sync"]
    I --> J["Zero-Footprint Purge & Clean Exit (Code 0)"]
```

### 8.3 Security & Execution Comparison Table

| Capability | Standard User Task | Unattended Windows System Service |
| :--- | :--- | :--- |
| **Account Context** | Current Logged-in User | `NT AUTHORITY\SYSTEM` |
| **Privilege Level** | `/rl LIMITED` (Standard User) | `/rl HIGHEST` (Full System Administrator) |
| **Session Isolation** | Interactive User Desktop | **Session 0** (Protected Server Isolation) |
| **Survives RDP Disconnects?** | ❌ Aborted if user logs off | ✅ **100% Immune to RDP Logoffs** |
| **Executes on Headless Boot?**| ❌ Requires user login | ✅ **Executes at System Startup** |
| **UAC Elevation Required?** | ❌ None (No Admin Needed) | ✅ One-Time UAC Elevation (Automatic) |
| **Command-Line Runner** | `DatabaseBackupApp.exe --auto` | `DatabaseBackupApp.exe --auto` / `--daemon` |

### 8.4 Continuous Background Daemon Runner (`--daemon` / `--service`)
In addition to scheduled weekly triggers, `auto_backup.py` includes a continuous daemon runner (`run_daemon_mode()`):
* Runs silently in Session 0 with minimal CPU and memory overhead (~35 MB).
* Awakens periodically (every 30 seconds) to evaluate scheduled day and time conditions.
* Triggers the full backup and telemetry sync, logging status to `backup_log.txt`.

---

## 9. Thread-Safe Emergency Stop & Cancellation Architecture

Large database backups (often exceeding several gigabytes) and multi-megabyte Google Drive uploads can take considerable time. If a system operator needs to halt execution immediately (e.g. to perform emergency server maintenance or relieve I/O pressure), the application provides a **thread-safe cancellation coordinator**.

### 9.1 Cancellation Sequence Diagram

```mermaid
sequenceDiagram
    participant User as User / Admin (GUI Button)
    participant Ctrl as BackupCancellationController
    participant Worker as Background Daemon Worker
    participant SQL as sqlcmd Subprocess (OS Level)
    participant Cloud as Google Drive Upload Stream (2MB Chunks)
    participant Disk as Local Storage Drive

    User->>Ctrl: stop_active_backup() [Button Click]
    Ctrl->>Ctrl: _cancelled.set()
    Ctrl->>SQL: proc.terminate() / proc.kill()
    SQL-->>Worker: Subprocess Terminated Immediately
    Worker->>Cloud: Check is_cancelled() before next 2MB chunk
    Worker->>Cloud: Abort active HTTP socket connection
    Worker->>Disk: Purge partial .bak or .zip files
    Worker-->>User: UI updates to "● BACKUP ABORTED BY USER"
```

### 9.2 Technical Implementation Details
1. **`BackupCancellationController` Singleton**:
   * Uses a thread-safe `threading.Event()` to broadcast cancellation signals across all running worker threads.
   * Tracks active OS subprocess handles (`_active_proc`) protected by a `threading.Lock()`.
2. **Immediate Subprocess Termination**:
   * Calling `stop_active_backup()` instantly terminates the child `sqlcmd.exe` process, releasing database table locks and file handles immediately.
3. **Resumable Upload Interruption**:
   * Google Drive uploads stream in discrete **2 MB chunks**. Before each chunk is transmitted over the network socket, the worker verifies `is_cancelled()`. If cancelled, the network socket is closed immediately.
4. **Zero Residual Corruption**:
   * When an abort occurs, the engine purges any incomplete `.bak` or `.zip` files from disk, ensuring that no corrupt or partial archive files remain.

---

## 10. SQL Server Error 5 & Msg 3201 Auto-Failover Engine

A frequent failure mode on locked-down client machines and Windows Servers is **Operating System Error 5 (Access is denied)**:
> `Cannot open backup device 'C:\Users\...\Desktop\backup.bak'. Operating system error 5 (Access is denied). Msg 3013, Level 16, Msg 3201.`

### 10.1 Root Cause Analysis
Microsoft SQL Server runs as a dedicated Windows service account (e.g. `NT SERVICE\MSSQLSERVER` or `NT SERVICE\MSSQL$SQLEXPRESS`). By default, Windows restricts service accounts from writing into user profiles (`C:\Users\<User>\Desktop` or `Documents`), even if the user running the GUI has full administrative privileges.

### 10.2 The Autonomous Self-Healing Pipeline

```mermaid
flowchart TD
    A["Initiate SQL Backup to Target Folder<br/>(e.g., C:\\temp\\backups or Desktop)"] --> B["Proactive icacls Grant<br/>(*S-1-1-0 Everyone & *S-1-5-32-545 Users)"]
    B --> C["Execute sqlcmd -b -l 15 -S ... -Q BACKUP DATABASE"]
    C --> D{"Backup Succeeded?"}
    D -->|"Yes (Code 0)"| E["Proceed to Level 9 ZIP Compression"]
    D -->|"No (Error 5 / Msg 3201: Access Denied)"| F["Trap SQL Server Service Account Restriction"]
    F --> G["Query SERVERPROPERTY('InstanceDefaultBackupPath')"]
    G --> H["Execute Failover Backup directly to SQL Authorized Path"]
    H --> I["Compress .bak directly into Target Folder as .zip"]
    I --> J["Purge temporary .bak from SQL Directory"]
    J --> E
```

### 10.3 Resilience Mechanisms
1. **Proactive Language-Neutral ACL Grants**:
   Before initiating backups, `grant_sql_folder_permissions()` uses Windows `icacls` to grant modify rights to language-neutral well-known SIDs:
   * `*S-1-1-0`: Well-known SID for **Everyone**.
   * `*S-1-5-32-545`: Well-known SID for **Builtin Users**.
2. **Native Failover Query**:
   If Error 5 persists, the engine queries the SQL Server engine's internal authorized directory:
   ```sql
   SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS VARCHAR(500))
   ```
   The engine writes the `.bak` there (where SQL Server is guaranteed full write permissions), compresses the archive directly into the user's destination directory, and purges the temporary `.bak`.
3. **Enterprise Server Flags (`-b -l 15`)**:
   All `sqlcmd` commands include:
   * `-b`: Batch abort on error (ensures nonzero exit code on SQL errors).
   * `-l 15`: 15-second login timeout to prevent indefinite hangs across high-latency VPN/RDP tunnels.
   * `timeout=15` on `subprocess.run` to guarantee no orphan processes remain.

---

## 11. Enterprise Clean Uninstallation Architecture & Self-Migrating Batch Pattern

To comply with enterprise IT software lifecycle standards, the application features a clean, complete uninstallation architecture with **zero leftovers**.

### 11.1 The File-Locking Challenge in Windows
When an uninstaller batch script (`Uninstall.bat`) is launched from inside the application directory (`C:\...\Programs\DatabaseBackupApp\Uninstall.bat`), `cmd.exe` maintains an open file handle on the batch file and locks the working directory. Any attempt by `rmdir /s /q` to delete the directory fails with *"Access is denied"*.

### 11.2 The Self-Migrating Batch Pattern

```mermaid
flowchart TD
    A["Uninstall Triggered<br/>(App Folder / GUI Button / Windows Apps)"] --> B{"Is running inside %TEMP%?"}
    B -->|"No (Running in App Folder)"| C["Copy script to %TEMP%\\Uninstall_DatabaseBackupApp.bat"]
    C --> D["Launch Temp Script & Terminate Original Process<br/>(Releases folder lock!)"]
    D --> E["cd /d %TEMP% (Safe Execution Context)"]
    B -->|"Yes"| E
    E --> F["Terminate Active Processes<br/>DatabaseBackupApp.exe, python.exe, sqlcmd.exe"]
    F --> G["Delete Windows Tasks & Services<br/>Database Cloud Backup, (System Service), Service"]
    G --> H["Remove Shortcuts<br/>Desktop, Start Menu, OneDrive redirected Desktop"]
    H --> I["Delete Windows Registry Entry<br/>HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"]
    I --> J["Purge Application Directory (%TARGET_DIR%)<br/>Recursive rmdir + PowerShell fallback"]
    J --> K["Display Completion Dialog & Del temp script"]
```

### 11.3 Four Ways to Uninstall
1. **Inside Application Folder**: Run `Uninstall.bat` directly inside `%LocalAppData%\Programs\DatabaseBackupApp\`.
2. **Inside Application GUI**: Go to **Settings** tab &rarr; **Application Lifecycle** &rarr; click **🗑️ Uninstall Application**.
3. **Windows Settings**: Go to **Settings &rarr; Apps &rarr; Installed Apps** &rarr; click **Uninstall** on *Database Cloud Backup*.
4. **From Package Root**: Run `Uninstall.bat` in the deployment directory.

---

## 12. Senior Engineering Review & Defense Cheat Sheet

| Reviewer Question | Comprehensive Technical Answer |
| :--- | :--- |
| **"Why is your engine separated from the GUI?"** | "Model-View separation. `backup_core.py` is 100% headless, stateless, and thread-safe. It can be called by the CustomTkinter GUI, by a CLI batch runner, or by Windows Task Scheduler with zero duplicated code." |
| **"How do you prevent the desktop UI from freezing during 500 MB uploads?"** | "All heavy I/O operations are dispatched onto Python daemon worker threads (`threading.Thread(target=..., daemon=True)`). Log streaming and progress bar updates are safely marshaled back to the Tkinter event loop using `self.after()`." |
| **"How do you guarantee clean uninstallation without file locks?"** | "We implement the Self-Migrating Batch Pattern: when launched, `Uninstall.bat` copies itself to `%TEMP%`, launches the temp instance with working directory switched to `%TEMP%`, and terminates the original process. This releases all Windows directory and file locks, allowing `rmdir` to cleanly purge the entire application folder." |
| **"How does the software handle SQL Server Error 5 (Access Denied)?"** | "The software uses a two-tier strategy: first, proactive NTFS ACL grants using language-neutral SIDs (`*S-1-1-0` and `*S-1-5-32-545`). Second, automatic runtime trapping: if Error 5 occurs, it queries SQL Server's native `SERVERPROPERTY('InstanceDefaultBackupPath')`, redirects the `.bak` there, compresses it to the destination, and deletes the temporary `.bak`." |
| **"How does the system ensure reliability on Windows Server and RDP?"** | "We provide an Unattended Windows System Service mode running under `NT AUTHORITY\SYSTEM` in Session 0. It executes before any user logs in, survives server reboots via startup triggers, and is completely immune to disconnected RDP sessions. All `sqlcmd` invocations include `-b` and `-l 15` timeout flags." |
| **"How do you manage client hard drive capacity?"** | "We implement an automated two-phase purge: the raw `.bak` is deleted immediately upon Level 9 ZIP creation, and the `.zip` archive is automatically deleted once Google Drive confirms the upload and Google Sheets logs the audit record (`DELETE_LOCAL_AFTER_UPLOAD: true`). This maintains a zero-byte persistent footprint." |
| **"Why did you include `-C` in the `sqlcmd` invocation?"** | "Microsoft ODBC Driver 18 introduced mandatory SSL/TLS encryption by default. `-C` ('Trust Server Certificate') allows the connection to trust self-signed local database certificates without failing." |
| **"What happens if an operator needs to cancel an active backup?"** | "The `BackupCancellationController` instantly signals worker threads, terminates the running `sqlcmd.exe` child process, aborts the 2MB chunked Google Drive upload stream, and purges all partial files from disk so zero corrupt data remains." |

