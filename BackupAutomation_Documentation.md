# Enterprise Database Cloud Backup Automation System
**Comprehensive Technical Architecture, Engineering Documentation & Operational Runbook**

---

<div align="center">
  <img src="./docs/images/app_icon.png" alt="Database Cloud Backup Logo" width="100">
  <br>
  <h1>Enterprise Database Cloud Backup Automation</h1>
  <p><strong>Autonomous Zero-Touch SQL Server Cloud Disaster Recovery & Telemetry Pipeline</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20%7C%20Server-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Platform">
    <img src="https://img.shields.io/badge/Engine-Python%203.x%20(Decoupled)-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/Database-Microsoft%20SQL%20Server-CC2927?style=for-the-badge&logo=microsoftsqlserver&logoColor=white" alt="SQL Server">
    <img src="https://img.shields.io/badge/Cloud-Google%20Drive%20v3%20%26%20Sheets%20v4-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="Google Cloud">
  </p>
</div>

---

## 1. Executive Summary

The **Enterprise Database Cloud Backup Automation System** is an industrial-grade, client-side backup and disaster recovery solution engineered specifically for Microsoft SQL Server environments across Windows Server, Remote Desktop Services (RDS/RDP), and standalone workstations.

It replaces fragile third-party tools and complex backup licensing models with a high-performance, autonomous native engine. Built on a clean **Model-View-Controller (MVC)** separation, the system pairs a headless, thread-safe core engine (`backup_core.py`) with a modern Windows 11 CustomTkinter desktop interface (`app_gui.py`), an autonomous deployment wizard (`installer_gui.py`), and a self-migrating clean uninstallation system (`Uninstall.bat`).

### Core Business & Technical Objectives
1. **100% Unattended Reliability:** Executes in Session 0 as an isolated Windows System Service (`NT AUTHORITY\SYSTEM`), surviving machine reboots, headless boots, and disconnected RDP sessions.
2. **Zero Local Storage Overhead:** Implements a two-phase cleanup pipeline that completely purges both raw `.bak` files and compressed `.zip` archives upon cloud verification, maintaining a zero-byte persistent footprint.
3. **Autonomous Self-Healing:** Detects and overcomes Windows NTFS directory security barriers and SQL Server Service Account restrictions (`Operating system error 5: Access is denied`) via dynamic native path failover.
4. **Immediate Operator Control:** Incorporates a thread-safe Emergency Stop controller (`🛑 STOP BACKUP`) capable of aborting active SQL processes, terminating child subroutines, severing network streams, and purging partial data in under 500 milliseconds.
5. **Centralized Compliance Telemetry:** Streams real-time audit records into a centralized Google Sheet, furnishing infrastructure teams with instant visibility across all client deployments.

---

## 2. End-to-End System Architecture

The architecture strictly decouples the core backup logic from the user presentation layer. The core engine is stateless, multi-thread safe, and completely free of GUI library imports.

### 2.1 High-Level Architecture Diagram

```mermaid
flowchart TD
    subgraph TriggerLayer["1. Trigger & Activation Layer"]
        T1["Interactive User Launch<br/>(Desktop Shortcut / Start Menu)"]
        T2["Windows Task Scheduler<br/>(Weekly Monday 02:00 AM)"]
        T3["Windows System Service<br/>(Session 0 Daemon --daemon)"]
    end

    subgraph EntryPoint["2. Dual-Mode Router (auto_backup.py)"]
        R{"CLI Flags Present?"}
        T1 --> R
        T2 --> R
        T3 --> R
        R -->|"No Flags"| GUI["Launch CustomTkinter GUI<br/>(app_gui.py)"]
        R -->|"--auto"| Headless["Headless Silent Runner<br/>(auto_backup.py)"]
        R -->|"--daemon"| Daemon["Continuous Session 0 Service<br/>(auto_backup.py)"]
    end

    subgraph EngineLayer["3. Stateless Core Engine (backup_core.py)"]
        Core["Orchestrator: run_full_backup()"]
        GUI -.->|"Dispatch on Worker Thread"| Core
        Headless --> Core
        Daemon --> Core
    end

    subgraph PipelineExecution["4. Autonomous Five-Stage Pipeline"]
        S1["Stage 1: Google OAuth 2.0 Auth & Refresh"]
        S2["Stage 2: SQL Server Extraction & Error 5 Failover"]
        S3["Stage 3: Level 9 Maximum Deflate Compression"]
        S4["Stage 4: Resumable Chunked Google Drive Upload"]
        S5["Stage 5: Google Sheets Telemetry Audit Record"]
        Core --> S1 --> S2 --> S3 --> S4 --> S5
    end

    subgraph CleanupLayer["5. Zero-Footprint Storage Purge"]
        P1["Phase 1: Delete .bak after ZIP verification"]
        P2["Phase 2: Delete .zip after Drive & Sheets confirmation"]
        S3 -.-> P1
        S5 -.-> P2
    end
```

---

## 3. End-to-End Sequence Diagram

The following sequence illustrates the full transaction lifecycle from initiation to cloud verification and storage cleanup:

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator / Scheduler
    participant UI as CustomTkinter GUI (app_gui)
    participant Core as Stateless Engine (backup_core)
    participant SQL as Microsoft SQL Server (sqlcmd)
    participant Disk as Local File Storage
    participant Drive as Google Drive API v3
    participant Sheet as Google Sheets API v4

    Op->>UI: Click "🚀 Start Full Backup Now" (or --auto)
    UI->>Core: Dispatch run_full_backup() on daemon worker thread
    Core->>Drive: Validate OAuth 2.0 Token (Auto-refresh if expired)
    Drive-->>Core: Token Valid (Active Session)

    loop For each Target Database
        Core->>SQL: Execute BACKUP DATABASE with FORMAT (-b -l 15)
        alt Directory Access Permitted
            SQL->>Disk: Write raw DB_Name.bak
        else Operating System Error 5 (Access Denied)
            Core->>SQL: Query SERVERPROPERTY('InstanceDefaultBackupPath')
            SQL-->>Core: Authorized SQL Server default path
            Core->>SQL: Execute backup to authorized path
            SQL->>Disk: Write temporary .bak to SQL directory
        end

        Core->>Disk: Compress .bak to Level 9 Deflate .zip
        Core->>Disk: Phase 1 Cleanup: Delete raw .bak immediately
        
        Core->>Drive: Stream .zip in 2MB/5MB resumable chunks
        Drive-->>Core: Upload complete (File ID returned)
        Core->>Drive: Set public reader permissions & fetch share link

        Core->>Sheet: Append compliance row [Timestamp, Name, Size, URL]
        Sheet-->>Core: Telemetry row committed

        Core->>Disk: Phase 2 Cleanup: Delete .zip archive from disk
        Core-->>UI: Post thread-safe event: "Backup Complete (0 bytes left)"
    end
    UI-->>Op: Display Success Notification
```

---

## 4. Key Engineering Innovations & Breakthroughs

### 4.1 Unattended Windows System Service & Session 0 Isolation
In mission-critical enterprise environments, servers reboot automatically during weekend maintenance windows, remaining at the Windows lock screen without any interactive user logged in. Furthermore, administrators connected via Remote Desktop (RDP) frequently disconnect, which abruptly kills traditional user-space scheduled tasks.

* **Execution Context:** The service executes under `NT AUTHORITY\SYSTEM` with `/rl HIGHEST`.
* **Session 0 Security:** Operates completely isolated in Windows Session 0, immune to interactive user logoffs, profile locks, or RDP disconnects.
* **Continuous Background Polling (`--daemon`):** When deployed with `--daemon` or `--service`, `auto_backup.py` polls scheduled execution triggers while maintaining an ultra-lightweight memory profile (~35 MB).

```
+-------------------------------------------------------------------------+
|                           WINDOWS SERVER HOST                           |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  | [SESSION 0] PROTECTED SYSTEM SERVICES (NON-INTERACTIVE)           |  |
|  |                                                                   |  |
|  |   +-------------------------------------------------------------+ |  |
|  |   | Database Cloud Backup (System Service)                     | |  |
|  |   | Context: NT AUTHORITY\SYSTEM | Level: /rl HIGHEST           | |  |
|  |   | Survives Reboots, Survives RDP Signouts, 100% Unattended    | |  |
|  |   +-------------------------------------------------------------+ |  |
|  +-------------------------------------------------------------------+  |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  | [SESSION 1+] INTERACTIVE USER CONTEXT (RDP / CONSOLE)             |  |
|  |                                                                   |  |
|  |   +------------------------------------+                          |  |
|  |   | Administrator RDP Session          |                          |  |
|  |   | (May log off, disconnect, or lock) |                          |  |
|  |   +------------------------------------+                          |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
```

---

### 4.2 Self-Healing SQL Server Error 5 (Operating System Error 5: Access is Denied)

A frequent failure on locked-down client machines occurs when SQL Server is requested to write directly to a user's desktop or documents folder:
```text
Cannot open backup device 'C:\Users\Admin\Desktop\backup.bak'.
Operating system error 5 (Access is denied).
Msg 3013, Level 16, State 1, Msg 3201.
```

#### Cause
Microsoft SQL Server runs under a dedicated virtual service account (`NT SERVICE\MSSQLSERVER` or `NT SERVICE\MSSQL$SQLEXPRESS`). By default, Windows NTFS security prevents service accounts from writing into user profiles, even if the user running the application is a full local administrator.

#### The Autonomous Self-Healing Pipeline
```mermaid
flowchart TD
    A["Target Backup Path<br/>(e.g., C:\\temp\\backups)"] --> B["Proactive icacls Grant<br/>(*S-1-1-0 Everyone & *S-1-5-32-545 Users)"]
    B --> C["Execute sqlcmd -b -l 15"]
    C --> D{"Backup Succeeded?"}
    D -->|"Yes (Code 0)"| E["Proceed to Level 9 ZIP"]
    D -->|"Error 5 / Msg 3201"| F["Trap SQL Service Account Restriction"]
    F --> G["Query SERVERPROPERTY('InstanceDefaultBackupPath')"]
    G --> H["Execute Backup into SQL Engine's Authorized Directory"]
    H --> I["Compress .bak directly into Target Folder as .zip"]
    I --> J["Purge temporary .bak from SQL Directory"]
    J --> E
```

1. **Proactive Language-Neutral ACL Grants:** Uses well-known security identifiers (`*S-1-1-0` for Everyone, `*S-1-5-32-545` for Built-in Users) to avoid localization crashes on non-English Windows editions.
2. **Native Failover Query:** Queries SQL Server's internal configuration:
   ```sql
   SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS VARCHAR(500))
   ```
3. Writes the temporary `.bak` to the guaranteed-accessible engine folder, streams it directly into a Level 9 `.zip` archive in the destination directory, and immediately purges the temporary `.bak`.

---

### 4.3 Thread-Safe Emergency Stop & Cancellation Architecture

Enterprise databases often scale to hundreds of gigabytes. If an operator requires immediate system relief during an active backup, clicking `"🛑 STOP BACKUP"` triggers the `BackupCancellationController`:

```mermaid
sequenceDiagram
    autonumber
    participant User as Operator (GUI Button)
    participant Ctrl as BackupCancellationController
    participant Worker as Background Daemon Worker
    participant SQL as sqlcmd Subprocess (OS Level)
    participant Cloud as Google Drive Resumable Stream
    participant Disk as Local File Storage

    User->>Ctrl: stop_active_backup()
    Ctrl->>Ctrl: Set thread-safe _cancelled event
    Ctrl->>SQL: proc.terminate() / proc.kill() (Immediate child kill)
    SQL-->>Worker: Subprocess aborted with nonzero returncode
    Worker->>Cloud: Check is_cancelled() before next 2MB chunk
    Worker->>Cloud: Abort active HTTP socket connection
    Worker->>Disk: Purge incomplete .bak or .zip files
    Worker-->>User: UI updates to "● BACKUP ABORTED BY USER"
```

* **Instant Process Termination:** Immediately terminates active OS child processes (`sqlcmd.exe`), releasing database table locks.
* **Socket Disconnection:** Interrupts 2MB resumable Google Drive upload streams mid-transmission without waiting for multi-gigabyte transfers to complete.
* **Zero Residual Leftovers:** Cleans up partial `.bak` and `.zip` files so no corrupt files remain on disk.

---

### 4.4 Enterprise Clean Uninstallation Architecture (Self-Migrating Batch Pattern)

When an uninstaller batch script (`Uninstall.bat`) is launched from inside the application directory, `cmd.exe` holds an active lock on the file and its parent folder. Any attempt to run `rmdir /s /q` results in an *"Access is denied"* error.

The solution is the **Self-Migrating Batch Pattern**:

```mermaid
flowchart TD
    A["Uninstall Triggered<br/>(App Directory / GUI Button / Windows Apps)"] --> B{"Is running inside %TEMP%?"}
    B -->|"No"| C["Copy script to %TEMP%\\Uninstall_DatabaseBackupApp.bat"]
    C --> D["Launch Temp Script & Terminate Original Process<br/>(Releases Directory Lock!)"]
    D --> E["cd /d %TEMP% (Safe Execution Context)"]
    B -->|"Yes"| E
    E --> F["Terminate Active Processes<br/>DatabaseBackupApp.exe, python.exe, sqlcmd.exe"]
    F --> G["Delete Windows Tasks & System Services<br/>DatabaseBackupAutomation_Weekly, (System Service)"]
    G --> H["Remove Shortcuts<br/>Desktop, Start Menu, OneDrive redirected Desktop"]
    H --> I["Delete Windows Registry Entry<br/>HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall"]
    I --> J["Purge Application Directory (%TARGET_DIR%)<br/>Recursive rmdir + PowerShell fallback"]
    J --> K["Display Completion Dialog & Clean temp script"]
```

---

## 5. Visual Interface Walkthrough & Screenshots

### 5.1 Interactive Dashboard & Live Execution Logs
The desktop application provides full diagnostic visibility, live log streaming with severity color-coding, and one-click manual execution:

<div align="center">
  <img src="./docs/images/live_logs_dashboard.png" alt="Live Execution Logs & Dashboard" width="800">
  <br>
  <em>Figure 1: Desktop GUI Dashboard showing live execution diagnostics, active cards, and status telemetry</em>
</div>

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

---

### 5.2 Autonomous Setup Wizard
The client deployment package features a standalone wizard (`Setup_DatabaseBackup.exe`) requiring zero pre-installed runtimes:

<div align="center">
  <img src="./docs/images/setup_wizard.png" alt="Database Cloud Backup Setup Wizard" width="750">
  <br>
  <em>Figure 2: Standalone Installation Wizard with directory selection and automated service setup</em>
</div>

* **Target Directory Selection:** Allows administrators to install in standard user space or dedicated server drives.
* **Shortcut Management:** Creates high-resolution shortcuts across local and OneDrive-redirected desktops.
* **Automatic Service Registration:** Configures the unattended scheduled task or Windows System Service directly from the installer.

---

### 5.3 Google Cloud Platform & OAuth 2.0 Security
The application connects via Google Cloud's Production OAuth 2.0 pipeline, ensuring that backups land in dedicated user storage quotas (15GB free or Google Workspace) without domain delegation expenses:

<div align="center">
  <img src="./docs/images/google_oauth_branding.png" alt="Google Cloud Console OAuth 2.0 Configuration" width="800">
  <br>
  <em>Figure 3: Google Cloud Platform OAuth Consent Screen & Scopes Configuration</em>
</div>

* **Restricted Least-Privilege Scopes:**
  - `drive.file`: Grants read/write access **only** to files created by the application itself.
  - `spreadsheets`: Grants append access **only** to the designated compliance audit sheet.
* **Offline Token Rotation:** Acquires a persistent `refresh_token` that rotates hourly access tokens silently without user intervention.

---

## 6. Configuration & Credential Reference

### 6.1 `config.json` Specification

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `SQL_SERVER_NAME` | String | `localhost\SQLEXPRESS` | Name or network address of the SQL Server instance. |
| `SQL_USERNAME` | String | `""` | Optional SQL authentication login (leave empty for Windows Auth). |
| `SQL_PASSWORD` | String | `""` | Optional SQL authentication password. |
| `BACKUP_FOLDER` | String | `C:\temp\backups` | Target directory for backup staging and compression. |
| `BACKUP_EXTENSION` | String | `.zip` | Compression file extension. |
| `TARGET_DATABASES` | List[String] | `[]` | List of databases targeted for automatic backup cycles. |
| `GOOGLE_DRIVE_FOLDER_ID` | String | `""` | Target Google Drive folder alphanumeric identifier. |
| `GOOGLE_SHEET_ID` | String | `""` | Alphanumeric identifier of the compliance logging Google Sheet. |
| `STRICTLY_MONDAYS_ONLY` | Boolean | `true` | Restricts automated execution strictly to Mondays. |
| `SCHEDULE_TIME` | String | `"02:00"` | Daily execution time (24-hour HH:MM format). |
| `DELETE_LOCAL_AFTER_UPLOAD` | Boolean | `true` | Enables Phase 2 storage cleanup (maintains zero bytes persistent). |

---

## 7. Production Deployment & Operational Runbook

### Quick Client Deployment (3 Simple Steps)
1. **Extract Package:** Unpack `Client_Installation_Package.rar` onto the customer machine.
2. **Execute Installer:** Run `Setup_DatabaseBackup.exe` (or `1_Quick_Install.bat`).
3. **Authenticate Cloud Storage:**
   - Launch the application from the desktop shortcut.
   - Click `"🚀 Start Full Backup Now"` once.
   - A secure browser window opens. Log into the organization's Google Account and grant permission.
   - The token is saved permanently to `credentials.json`.
4. **Configure Unattended Automation:**
   - Navigate to the **⏰ Auto Schedule** tab.
   - Select **⚡ Unattended Windows System Service (Recommended for Servers / RDP)**.
   - Click **Save Schedule Settings**. The system is now 100% autonomous.

### Complete Uninstallation
To completely remove the software with zero residual files:
- Go to **Settings** in the desktop application &rarr; click **🗑️ Uninstall Application**, OR
- Run `Uninstall.bat` inside the installation folder (`%LOCALAPPDATA%\Programs\DatabaseBackupApp\Uninstall.bat`), OR
- Open Windows **Settings &rarr; Apps &rarr; Installed Apps** &rarr; select **Database Cloud Backup** &rarr; click **Uninstall**.

---

<div align="center">
  <p><strong>Database Cloud Backup Automation System</strong> — Engineered for Enterprise Resilience.</p>
</div>
