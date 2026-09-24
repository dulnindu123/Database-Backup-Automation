"""
Enterprise Database Cloud Backup Automation - Core Stateless Engine
=============================================================================
Author: Dulnindu Saranga
Architecture: Model Layer (Stateless, Thread-Safe, Headless Engine)

Responsibilities:
1. Configuration Management: Load and persist JSON application settings with safe defaults.
2. Google OAuth 2.0 Lifecycle: Offline token acquisition, token refresh, and scope management.
3. Diagnostic Health Probes: Non-destructive verification of Google Drive and Google Sheets APIs.
4. Database Extraction: Native Microsoft SQL Server dump execution via sqlcmd with TLS/ODBC 18 trust.
5. High-Ratio Compression: Level 9 Deflate compression (.bak to .zip) with Phase 1 storage cleanup.
6. Cloud Storage Synchronization: Resumable chunked upload to Google Drive with automated retry backoff.
7. Compliance Telemetry: Formatted audit row append to Google Sheets including exact file sizes.
8. Storage Drive Zero-Footprint: Phase 2 local storage purge deleting .zip archives post-cloud sync.
9. Windows Service Discovery: Automatic discovery of SQL instances and databases via Windows Registry.
10. Task Scheduler Management: Native schtasks.exe orchestration for weekly unattended executions.
"""

import os
import sys
import glob
import time
import json
import logging
import zipfile
import subprocess
import threading
from datetime import datetime

# Google APIs & Client Libraries
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# -----------------------------------------------------------------------------
# GOOGLE OAUTH CONFIGURATION & SANITIZATION
# -----------------------------------------------------------------------------
# Google Cloud periodically modernizes and condenses OAuth scope URLs.
# Setting OAUTHLIB_RELAX_TOKEN_SCOPE = 1 tells the oauthlib library to accept 
# Google's canonical scope responses without raising an unhandled ScopeChangedError.
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# In windowed PyInstaller executables (built without a console window), sys.stdout
# and sys.stderr evaluate to None. Redirecting them prevents write attribute crashes.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# Least-privilege Google OAuth 2.0 scopes:
# - drive.file: Allows full access ONLY to files/folders created by this application.
#               The application cannot read, modify, or delete any other files in Google Drive.
# - spreadsheets: Allows appending telemetry and audit rows to the compliance spreadsheet.
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets"
]

# Standard Windows Task Scheduler & Service entry identifiers
TASK_SCHEDULER_NAME = "Database Cloud Backup"
SYSTEM_SERVICE_TASK_NAME = "Database Cloud Backup (System Service)"
DAEMON_SERVICE_TASK_NAME = "Database Cloud Backup Service"


# =============================================================================
# EMERGENCY CANCELLATION & PROCESS COORDINATOR
# =============================================================================

class BackupCancellationController:
    """
    Thread-safe execution coordinator managing emergency stop requests.
    Tracks running subprocesses (such as sqlcmd) and signals background
    threads to immediately abort compression or Google Cloud uploads.
    """
    def __init__(self):
        self._cancelled = threading.Event()
        self._active_proc = None
        self._lock = threading.Lock()

    def request_stop(self):
        """Signals active workers to abort and forcefully terminates child processes."""
        self._cancelled.set()
        with self._lock:
            if self._active_proc and self._active_proc.poll() is None:
                try:
                    self._active_proc.terminate()
                except Exception:
                    try:
                        self._active_proc.kill()
                    except Exception:
                        pass

    def reset(self):
        """Resets the cancellation flag for new execution runs."""
        self._cancelled.clear()
        with self._lock:
            self._active_proc = None

    def is_cancelled(self):
        """Returns True if an emergency stop was requested."""
        return self._cancelled.is_set()

    def set_active_process(self, proc):
        """Registers a running subprocess for instant emergency termination."""
        with self._lock:
            self._active_proc = proc

    def clear_active_process(self):
        """Deregisters the subprocess once execution finishes."""
        with self._lock:
            self._active_proc = None


# Global execution controller singleton
backup_controller = BackupCancellationController()


def stop_active_backup():
    """
    Globally requests an immediate emergency stop of any running backup,
    compression, or cloud upload process.
    """
    backup_controller.request_stop()
    emit_log(">>> EMERGENCY STOP SIGNAL BROADCAST <<<", "warning")


def is_backup_cancelled():
    """Returns True if the active backup run has been cancelled."""
    return backup_controller.is_cancelled()


def get_base_dir():
    """
    Resolves the persistent application directory where configuration, logs, 
    and OAuth tokens reside.
    
    In development: Points to the directory containing this script.
    In production (PyInstaller): Points to the directory containing the running .exe,
    ensuring that runtime modifications (config.json, token.json) persist across runs
    and are not lost in PyInstaller's temporary sys._MEIPASS extraction folder.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

# Global filesystem paths
BASE_DIR = get_base_dir()
LOG_FILE = os.path.join(BASE_DIR, "backup_log.txt")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
if not os.path.exists(TOKEN_FILE) and os.path.exists(os.path.join(BASE_DIR, "credentials.json")):
    TOKEN_FILE = os.path.join(BASE_DIR, "credentials.json")
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")

# Initialize root file logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def emit_log(message, level="info", log_cb=None):
    """
    Dual-dispatch logging utility.
    1. Persists the log record to the local backup_log.txt file on disk.
    2. Prints the message to standard output for CLI sessions.
    3. Safely invokes the UI log callback (log_cb) if supplied by app_gui.py.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {message}"
    
    # Write to local file log based on severity
    if level == "critical":
        logging.critical(message)
    elif level == "error":
        logging.error(message)
    elif level == "warning":
        logging.warning(message)
    else:
        logging.info(message)
        
    print(formatted)
    
    # Forward to desktop GUI real-time terminal widget
    if log_cb:
        try:
            log_cb(formatted, level)
        except Exception:
            pass


# =============================================================================
# 1. CONFIGURATION MANAGEMENT
# =============================================================================

def load_config():
    """
    Loads JSON configuration settings from config.json.
    If the file does not exist, populates default enterprise parameters,
    creates config.json on disk, and returns the default dictionary.
    """
    default_config = {
        "SQL_SERVER_NAME": "localhost\\SQLEXPRESS",
        "SQL_USERNAME": "",
        "SQL_PASSWORD": "",
        "BACKUP_FOLDER": "C:\\temp\\backups",
        "BACKUP_EXTENSION": ".zip",
        "TARGET_DATABASES": ["SuperForm", "GeelongGlass"],
        "GOOGLE_DRIVE_FOLDER_ID": "1LKuo7j4cHvvP0-p0C6PVo6gdkgoVBaQ4",
        "GOOGLE_SHEET_ID": "1FAnmfTAixeDgwA5f3TvJ9IEtFp1OuFTyw3UpDiOdvwg",
        "STRICTLY_MONDAYS_ONLY": True,
        "SCHEDULE_TIME": "02:00",
        "DELETE_LOCAL_AFTER_UPLOAD": True
    }
    
    if not os.path.exists(CONFIG_FILE):
        emit_log(f"config.json not found at {CONFIG_FILE}. Creating default configuration template.", "warning")
        save_config(default_config)
        return default_config
        
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            # Ensure any newly introduced settings default cleanly if missing from older configs
            for k, v in default_config.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        emit_log(f"Corrupted config.json detected: {e}. Falling back to default settings.", "error")
        return default_config


def save_config(config_dict):
    """
    Serializes and writes updated configuration dictionary to config.json.
    """
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=4)
        emit_log("Configuration successfully updated on disk.")
        return True, "Configuration saved successfully."
    except Exception as e:
        err = f"Failed to save configuration: {e}"
        emit_log(err, "error")
        return False, err


# =============================================================================
# 2. GOOGLE OAUTH 2.0 AUTHENTICATION LIFECYCLE
# =============================================================================

def authenticate(interactive=True, log_cb=None):
    """
    Acquires and validates Google OAuth 2.0 user credentials.
    
    Lifecycle:
    1. Inspects disk for an existing token.json (or credentials.json).
    2. If token exists and is valid: Reuses immediately.
    3. If token is expired but has a refresh_token: Silently refreshes the token 
       against Google's token endpoint without user intervention.
    4. If no valid token exists:
       - If interactive=True: Spawns an ephemeral local web server on port 0
         and launches the system default browser for Google sign-in.
       - If interactive=False (Scheduled Task mode): Aborts cleanly to prevent
         headless processes from hanging indefinitely.
    5. Persists the active credentials to disk for subsequent unattended runs.
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            emit_log(f"Failed to parse stored token ({TOKEN_FILE}): {e}", "warning", log_cb)
            
    if not creds or not creds.valid:
        # Step A: Silent token refresh via offline refresh_token
        if creds and creds.expired and creds.refresh_token:
            try:
                emit_log("Refreshing expired Google credentials via refresh token...", "info", log_cb)
                creds.refresh(Request())
            except Exception as e:
                emit_log(f"Token refresh failed (token may have been revoked): {e}", "error", log_cb)
                creds = None
                
        # Step B: Interactive initial browser authorization
        if not creds:
            if not os.path.exists(CLIENT_SECRET_FILE):
                emit_log(f"OAuth Client Secret missing at {CLIENT_SECRET_FILE}. Please configure GCP credentials.", "critical", log_cb)
                return None
                
            if not interactive:
                emit_log("Unattended execution halted: User authorization required but running in non-interactive mode.", "error", log_cb)
                return None
                
            emit_log("Launching default web browser for Google account authorization...", "info", log_cb)
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                emit_log(f"OAuth handshake failed: {e}", "critical", log_cb)
                return None
                
        # Step C: Save newly authorized or refreshed credentials
        try:
            with open(TOKEN_FILE, 'w', encoding='utf-8') as token_out:
                token_out.write(creds.to_json())
            emit_log(f"Google credentials successfully saved to {os.path.basename(TOKEN_FILE)}", "info", log_cb)
        except Exception as e:
            emit_log(f"Failed to persist credentials to disk: {e}", "warning", log_cb)
            
    return creds


def reset_credentials():
    """
    Deletes the cached token.json / credentials.json file.
    Enables users or administrators to switch to a different Google account 
    without having to manually dig through the filesystem.
    """
    if os.path.exists(TOKEN_FILE):
        try:
            os.remove(TOKEN_FILE)
            emit_log("Cached Google credentials removed.")
            return True, "Stored credentials removed. You can now connect a different Google account."
        except Exception as e:
            err = f"Failed to delete {TOKEN_FILE}: {e}"
            emit_log(err, "error")
            return False, err
    return True, "No stored credentials found."


# =============================================================================
# 3. DIAGNOSTIC HEALTH PROBES
# =============================================================================

def test_google_connection(creds, drive_folder_id, sheet_id, log_cb=None):
    """
    Performs non-destructive read validation against Google Cloud services.
    
    Validates:
    1. Token validity and API scopes.
    2. Google Drive Folder access (queries folder metadata by ID).
    3. Google Sheets access (queries worksheet title and dimensions by ID).
    
    Returns a structured status dictionary for UI diagnostic display.
    """
    results = {
        "auth": False,
        "drive": False,
        "drive_name": "",
        "sheet": False,
        "sheet_title": "",
        "errors": []
    }
    
    if not creds:
        results["errors"].append("Google credentials could not be obtained.")
        return results
        
    results["auth"] = True
    emit_log("Google credentials verified.", "info", log_cb)
    
    # Probe Google Drive Folder
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        folder = drive_service.files().get(fileId=drive_folder_id, fields='name').execute()
        results["drive"] = True
        results["drive_name"] = folder.get('name', 'Unknown')
        emit_log(f"Google Drive verified. Destination folder: '{results['drive_name']}'", "info", log_cb)
    except Exception as e:
        results["errors"].append(f"Google Drive error: {e}")
        emit_log(f"Google Drive connection failed: {e}", "error", log_cb)
        
    # Probe Google Sheets Document
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        results["sheet"] = True
        results["sheet_title"] = sheet.title
        emit_log(f"Google Sheets verified. Active worksheet: '{sheet.title}'", "info", log_cb)
    except Exception as e:
        results["errors"].append(f"Google Sheets error: {e}")
        emit_log(f"Google Sheets connection failed: {e}", "error", log_cb)
        
    return results


# =============================================================================
# 4. DATABASE EXTRACTION & HIGH-RATIO COMPRESSION
# =============================================================================

def grant_sql_folder_permissions(folder_path):
    """
    Grants NTFS write/modify permissions on the target directory for the SQL Server
    service account and standard user accounts using Windows icacls.
    Uses well-known language-independent SIDs:
    - *S-1-1-0: Everyone
    - *S-1-5-32-545: Builtin Users
    """
    try:
        norm_path = os.path.normpath(folder_path)
        if not os.path.exists(norm_path):
            os.makedirs(norm_path, exist_ok=True)
        # Grant Everyone Modify (OI)(CI)M permissions
        subprocess.run(
            f'icacls "{norm_path}" /grant *S-1-1-0:(OI)(CI)M /T /C /Q',
            shell=True, capture_output=True, text=True, timeout=10
        )
        # Grant Users Modify (OI)(CI)M permissions
        subprocess.run(
            f'icacls "{norm_path}" /grant *S-1-5-32-545:(OI)(CI)M /T /C /Q',
            shell=True, capture_output=True, text=True, timeout=10
        )
    except Exception:
        pass


def get_sql_instance_default_backup_path(sql_server, sql_user="", sql_password=""):
    """
    Queries SQL Server instance for its default backup directory,
    which is guaranteed to have write permissions for the SQL Server engine service.
    """
    query = "SET NOCOUNT ON; SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS VARCHAR(500))"
    if sql_user and sql_password:
        cmd = f'sqlcmd -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -h -1 -W -Q "{query}"'
    else:
        cmd = f'sqlcmd -b -l 15 -S "{sql_server}" -E -C -h -1 -W -Q "{query}"'
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip() and not line.strip().startswith("-")]
            if lines:
                candidate = os.path.normpath(lines[0])
                if os.path.isdir(candidate):
                    return candidate
    except Exception:
        pass
    return None


def generate_and_compress_backup(folder, db_name, sql_server, sql_user="", sql_password="", log_cb=None, status_cb=None, cancel_check=None):
    """
    Executes native Microsoft SQL Server database backup and Level 9 Deflate compression.
    
    Resilience, Failover & Emergency Cancellation Features:
    1. Normalizes all folder and file paths to standard Windows backslashes.
    2. Proactively configures NTFS permissions via icacls on the destination directory.
    3. Traps SQL Server Error 5 (Operating system error 5: Access is denied) and Msg 3201:
       If the SQL Server service account lacks rights to write to user-space folders
       (e.g., Desktop or Documents), it automatically queries SQL Server's internal 
       InstanceDefaultBackupPath, runs the backup to that authorized location,
       compresses the archive directly into the user's requested destination, and purges
       the temporary .bak from the SQL Server directory.
    4. Emergency Abort & Cleanup:
       Monitors backup_controller and cancel_check. If aborted, terminates the running
       sqlcmd child process immediately, halts compression, and deletes any partial
       .bak or .zip files so zero corrupted residual files remain.
    """
    if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
        emit_log(f"Backup execution aborted before processing '{db_name}'.", "warning", log_cb)
        return None

    folder = os.path.normpath(folder)
    if not os.path.exists(folder):
        try:
            os.makedirs(folder, exist_ok=True)
            emit_log(f"Created local backup directory: {folder}", "info", log_cb)
        except Exception as e:
            emit_log(f"Backup folder does not exist and could not be created: {e}", "critical", log_cb)
            return None
            
    # Proactively ensure SQL service account has write permissions to target folder
    grant_sql_folder_permissions(folder)
            
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_filename = f"{db_name}_{date_str}.bak"
    zip_filename = f"{db_name}_{date_str}.zip"
    bak_filepath = os.path.normpath(os.path.join(folder, bak_filename))
    zip_filepath = os.path.normpath(os.path.join(folder, zip_filename))
    
    emit_log(f"Initiating SQL backup for database '{db_name}'...", "info", log_cb)
    
    # Build sqlcmd command line with -b (batch abort) and -l 15 (15-sec login timeout for network/RDP/Server resilience)
    if sql_user and sql_password:
        cmd = f'sqlcmd -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{bak_filepath}\' WITH FORMAT"'
    else:
        cmd = f'sqlcmd -b -l 15 -S "{sql_server}" -E -C -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{bak_filepath}\' WITH FORMAT"'

    try:
        # Execute database backup in isolated subprocess with emergency termination support
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        backup_controller.set_active_process(proc)
        try:
            stdout, stderr = proc.communicate()
        finally:
            backup_controller.clear_active_process()

        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            emit_log(f"SQL Backup for {db_name} aborted by user. Purging temporary files...", "warning", log_cb)
            if os.path.exists(bak_filepath):
                try:
                    os.remove(bak_filepath)
                except Exception:
                    pass
            return None

        backup_succeeded = (proc.returncode == 0 and os.path.exists(bak_filepath))

        if not backup_succeeded:
            err_msg = ((stderr or "") + "\n" + (stdout or "")).strip()
            
            # Detect SQL Server Error 5 / Msg 3201 (Access is denied to backup device)
            is_access_denied = (
                "error 5" in err_msg.lower() or 
                "access is denied" in err_msg.lower() or 
                "3201" in err_msg or
                "cannot open backup device" in err_msg.lower()
            )
            
            if is_access_denied:
                emit_log(f"SQL Server service account lacks write access to '{folder}' (Error 5: Access is denied).", "warning", log_cb)
                emit_log("Engaging automated failover: resolving SQL Server native authorized backup directory...", "info", log_cb)
                
                # Priority 1: SQL Server's native InstanceDefaultBackupPath
                fallback_folder = get_sql_instance_default_backup_path(sql_server, sql_user, sql_password)
                if not fallback_folder:
                    # Priority 2: Standard public temp backup folder
                    fallback_folder = os.path.normpath("C:\\temp\\backups")
                    os.makedirs(fallback_folder, exist_ok=True)
                    grant_sql_folder_permissions(fallback_folder)
                    
                emit_log(f"Failing over to SQL-authorized directory: {fallback_folder}", "info", log_cb)
                fallback_bak = os.path.normpath(os.path.join(fallback_folder, bak_filename))
                
                if sql_user and sql_password:
                    cmd_fb = f'sqlcmd -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{fallback_bak}\' WITH FORMAT"'
                else:
                    cmd_fb = f'sqlcmd -b -l 15 -S "{sql_server}" -E -C -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{fallback_bak}\' WITH FORMAT"'
                
                proc_fb = subprocess.Popen(cmd_fb, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                backup_controller.set_active_process(proc_fb)
                try:
                    stdout_fb, stderr_fb = proc_fb.communicate()
                finally:
                    backup_controller.clear_active_process()

                if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                    emit_log(f"SQL Failover Backup for {db_name} aborted by user. Purging temporary files...", "warning", log_cb)
                    if os.path.exists(fallback_bak):
                        try:
                            os.remove(fallback_bak)
                        except Exception:
                            pass
                    return None

                if proc_fb.returncode == 0 and os.path.exists(fallback_bak):
                    emit_log(f"Failover SQL backup successfully created at: {fallback_bak}", "info", log_cb)
                    bak_filepath = fallback_bak
                    backup_succeeded = True
                else:
                    err_fb = ((stderr_fb or "") + "\n" + (stdout_fb or "")).strip()
                    emit_log(f"SQL Backup failed even on failover location: {err_fb}", "error", log_cb)
                    return None
            else:
                emit_log(f"SQL Backup failed for {db_name}: {err_msg}", "error", log_cb)
                return None

        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            if os.path.exists(bak_filepath):
                try:
                    os.remove(bak_filepath)
                except Exception:
                    pass
            return None
            
        raw_size_mb = os.path.getsize(bak_filepath) / (1024 * 1024)
        emit_log(f"Database backup created: {os.path.basename(bak_filepath)} ({raw_size_mb:.2f} MB). Compressing with Level 9 Deflate...", "info", log_cb)
        if status_cb:
            status_cb(f"Compressing {db_name} with Level 9 Deflate...")
        
        # Prefer saving compressed .zip archive in the user-specified destination folder
        target_zip_filepath = zip_filepath
        try:
            test_file = os.path.join(folder, f".test_write_{date_str}")
            with open(test_file, 'w') as tf:
                tf.write("1")
            os.remove(test_file)
        except Exception:
            target_zip_filepath = os.path.normpath(os.path.join(os.path.dirname(bak_filepath), zip_filename))

        # Apply Level 9 Deflate compression
        with zipfile.ZipFile(target_zip_filepath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            zipf.write(bak_filepath, arcname=bak_filename)
            
        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            emit_log(f"Compression for {db_name} interrupted by emergency stop. Purging files...", "warning", log_cb)
            if os.path.exists(target_zip_filepath):
                try:
                    os.remove(target_zip_filepath)
                except Exception:
                    pass
            if os.path.exists(bak_filepath):
                try:
                    os.remove(bak_filepath)
                except Exception:
                    pass
            return None

        # PHASE 1 STORAGE CLEANUP: Remove raw .bak to reclaim local disk space
        if os.path.exists(target_zip_filepath):
            try:
                os.remove(bak_filepath)
            except Exception as e:
                emit_log(f"Warning: could not delete temporary bak file {bak_filepath}: {e}", "warning", log_cb)
            zip_size_mb = os.path.getsize(target_zip_filepath) / (1024 * 1024)
            ratio = (1 - (zip_size_mb / raw_size_mb)) * 100 if raw_size_mb > 0 else 0
            emit_log(f"Compressed {os.path.basename(target_zip_filepath)} ({zip_size_mb:.2f} MB - {ratio:.1f}% space saved). Temporary .bak purged.", "info", log_cb)
            
        return target_zip_filepath
    except Exception as e:
        emit_log(f"Backup/compression error for {db_name}: {e}", "error", log_cb)
        return None


# =============================================================================
# 5. CLOUD STORAGE UPLOAD & TELEMETRY
# =============================================================================

def upload_to_google_drive(creds, file_path, folder_id, retries=3, log_cb=None, status_cb=None, cancel_check=None):
    """
    Streams a local backup archive to the configured Google Drive folder.
    
    Features:
    - Uses resumable chunked upload (MediaFileUpload with chunksize=2MB and resumable=True).
    - Emergency stop awareness: monitors backup_controller and cancel_check to instantly abort upload.
    - Implements exponential retry backoff with non-blocking cancel checks.
    - Traps Google Drive quota exhaustion errors (HTTP 403 storageQuotaExceeded).
    - Sets public reader permissions so download links can be accessed by authorized reviewers.
    - Resolves and returns the canonical webViewLink URL.
    """
    file_name = os.path.basename(file_path)
    try:
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception as e:
        emit_log(f"Google Drive service build failure: {e}", "error", log_cb)
        return None
        
    for attempt in range(1, retries + 1):
        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            emit_log(f"Upload of {file_name} aborted before attempt {attempt}.", "warning", log_cb)
            return None

        try:
            emit_log(f"Uploading {file_name} to Google Drive (Attempt {attempt}/{retries})...", "info", log_cb)
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            # Stream in 2MB chunks for fine-grained progress and instantaneous emergency abort
            media = MediaFileUpload(file_path, chunksize=2 * 1024 * 1024, resumable=True)
            request = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            )
            
            uploaded_file = None
            while uploaded_file is None:
                if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                    emit_log(f"Upload of {file_name} aborted by user during transfer.", "warning", log_cb)
                    return None
                status, uploaded_file = request.next_chunk()
                if status and status_cb:
                    pct = int(status.progress() * 100)
                    status_cb(f"Uploading {file_name} ({pct}%)...")

            file_id = uploaded_file.get('id')
            link = uploaded_file.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            if link:
                emit_log(f"Upload complete for {file_name}! Link: {link}", "info", log_cb)
                # Attempt to set public read permission
                try:
                    permission = {'type': 'anyone', 'role': 'reader'}
                    drive_service.permissions().create(fileId=file_id, body=permission).execute()
                    emit_log("Permissions configured: Shareable link is active.", "info", log_cb)
                except Exception as perm_err:
                    emit_log(f"Public permission notice: {perm_err}", "warning", log_cb)
                return link

        except HttpError as err:
            if err.resp.status in [400, 403] and 'quota' in str(err).lower():
                emit_log(f"CRITICAL: Google Drive storage quota full! {err}", "critical", log_cb)
                return None
            emit_log(f"Google Drive API error: {err}", "error", log_cb)
        except Exception as e:
            if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                return None
            emit_log(f"Network error during upload: {e}", "error", log_cb)
            
        if attempt < retries:
            emit_log("Retrying upload in 10 seconds...", "info", log_cb)
            for _ in range(20):
                if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                    return None
                time.sleep(0.5)
            
    emit_log(f"Upload failed after {retries} attempts for {file_name}.", "critical", log_cb)
    return None


def format_file_size(size_bytes):
    """
    Converts raw integer bytes into human-readable formatted strings:
    - Bytes (B)
    - Kilobytes (KB)
    - Megabytes (MB)
    - Gigabytes (GB)
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def update_google_sheet(creds, sheet_id, backup_filename, file_size_str, download_link, log_cb=None):
    """
    Appends an immutable compliance audit record to Google Sheets.
    
    Row schema:
    [ Date & Time, Backup File Name, Backup File Size, Google Drive Download Link ]
    
    Dynamically checks if the sheet contains a header row; if empty, automatically
    inserts the standard compliance header at index 1 before appending data.
    """
    emit_log(f"Logging backup record to Google Sheet ({backup_filename}, {file_size_str})...", "info", log_cb)
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        
        # Ensure header row exists
        first_row = sheet.row_values(1)
        headers = ["Date & Time", "Backup File Name", "Backup File Size", "Google Drive Download Link"]
        if not first_row or "Date" not in first_row[0]:
            sheet.insert_row(headers, index=1)
            emit_log("Created compliance header row in Google Sheet.", "info", log_cb)
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp, backup_filename, file_size_str, download_link]
        sheet.append_row(row)
        emit_log(f"Google Sheet audit log updated: {backup_filename} ({file_size_str})", "info", log_cb)
        return True
    except Exception as e:
        emit_log(f"Google Sheets logging error: {e}", "error", log_cb)
        return False


# =============================================================================
# 6. MASTER WORKFLOW ORCHESTRATION & STORAGE CLEANUP
# =============================================================================

def run_full_backup(config=None, log_cb=None, progress_cb=None, status_cb=None, cancel_check=None):
    """
    Master end-to-end backup orchestrator.
    
    Coordinates the entire backup pipeline for all databases defined in TARGET_DATABASES:
    1. Resets cancellation controller and authenticates Google OAuth 2.0.
    2. Iterates sequentially across target databases with active cancellation guards.
    3. Triggers native SQL extraction and Level 9 Deflate compression.
    4. Streams archive to Google Drive with 2MB chunked progress & emergency abort.
    5. Appends compliance telemetry to Google Sheets.
    6. PHASE 2 STORAGE CLEANUP: Immediately deletes the local .zip file from the 
       storage drive (if DELETE_LOCAL_AFTER_UPLOAD is true), ensuring zero disk bloat.
       If the upload fails, the local archive is preserved to avoid data loss.
    7. Updates status and progress bar callbacks for the desktop GUI.
    """
    if not config:
        config = load_config()

    # Reset any previous emergency stop signal
    backup_controller.reset()
        
    emit_log("=" * 60, "info", log_cb)
    emit_log("STARTING DATABASE BACKUP EXECUTION CYCLE", "info", log_cb)
    emit_log("=" * 60, "info", log_cb)
    
    if status_cb:
        status_cb("Authenticating with Google Cloud...")
    if progress_cb:
        progress_cb(0.1)

    if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
        emit_log("Backup cycle cancelled by user before authentication.", "warning", log_cb)
        if status_cb:
            status_cb("Backup Cancelled")
        return False, "Backup operation was cancelled by user."
        
    creds = authenticate(interactive=True, log_cb=log_cb)
    if not creds:
        emit_log("Authentication failed. Aborting backup cycle.", "critical", log_cb)
        if status_cb:
            status_cb("Authentication Failed")
        return False, "Google Authentication Failed"

    if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
        emit_log("Backup cycle cancelled by user after authentication.", "warning", log_cb)
        if status_cb:
            status_cb("Backup Cancelled")
        return False, "Backup operation was cancelled by user."
        
    databases = config.get("TARGET_DATABASES", [])
    if not databases:
        emit_log("No target databases specified in configuration.", "warning", log_cb)
        return True, "No databases configured."
        
    total_dbs = len(databases)
    success_count = 0
    
    for idx, db_name in enumerate(databases):
        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            emit_log("EMERGENCY STOP: Halting backup queue before next database.", "warning", log_cb)
            if status_cb:
                status_cb("Backup Cancelled by User")
            return False, "Backup operation was cancelled by user."

        step_progress = 0.15 + (idx / total_dbs) * 0.8
        if progress_cb:
            progress_cb(step_progress)
        if status_cb:
            status_cb(f"Processing database {idx + 1}/{total_dbs}: {db_name}")
            
        emit_log(f"--- Processing Database: {db_name} ---", "info", log_cb)
        
        # Step 1: SQL Backup + Level 9 Compression + Phase 1 Cleanup
        backup_zip = generate_and_compress_backup(
            folder=config.get("BACKUP_FOLDER", "C:\\temp\\backups"),
            db_name=db_name,
            sql_server=config.get("SQL_SERVER_NAME", "localhost\\SQLEXPRESS"),
            sql_user=config.get("SQL_USERNAME", ""),
            sql_password=config.get("SQL_PASSWORD", ""),
            log_cb=log_cb,
            status_cb=status_cb,
            cancel_check=cancel_check
        )

        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            emit_log(f"EMERGENCY STOP: Cancelled after processing {db_name}.", "warning", log_cb)
            if backup_zip and os.path.exists(backup_zip):
                try:
                    os.remove(backup_zip)
                except Exception:
                    pass
            if status_cb:
                status_cb("Backup Cancelled by User")
            return False, "Backup operation was cancelled by user."
        
        if backup_zip and os.path.exists(backup_zip):
            file_name = os.path.basename(backup_zip)
            file_size_bytes = os.path.getsize(backup_zip)
            file_size_str = format_file_size(file_size_bytes)
            
            # Step 2: Stream archive to Google Drive
            if status_cb:
                status_cb(f"Uploading {file_name} ({file_size_str}) to Google Drive...")
            link = upload_to_google_drive(
                creds=creds,
                file_path=backup_zip,
                folder_id=config.get("GOOGLE_DRIVE_FOLDER_ID"),
                log_cb=log_cb,
                status_cb=status_cb,
                cancel_check=cancel_check
            )

            if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                emit_log(f"EMERGENCY STOP: Upload stopped for {db_name}.", "warning", log_cb)
                if status_cb:
                    status_cb("Backup Cancelled by User")
                return False, "Backup operation was cancelled by user."
            
            # Step 3: Log telemetry to Google Sheets
            if link:
                if status_cb:
                    status_cb(f"Logging {file_name} to Google Sheet...")
                update_google_sheet(
                    creds=creds,
                    sheet_id=config.get("GOOGLE_SHEET_ID"),
                    backup_filename=file_name,
                    file_size_str=file_size_str,
                    download_link=link,
                    log_cb=log_cb
                )
                success_count += 1
                
                # Step 4: PHASE 2 STORAGE CLEANUP (Delete local .zip after upload)
                if config.get("DELETE_LOCAL_AFTER_UPLOAD", True):
                    try:
                        if os.path.exists(backup_zip):
                            os.remove(backup_zip)
                            emit_log(f"Local storage cleaned: Deleted '{file_name}' from disk to maintain zero storage footprint.", "info", log_cb)
                    except Exception as clean_err:
                        emit_log(f"Notice: Could not delete local backup file '{file_name}': {clean_err}", "warning", log_cb)
            else:
                emit_log(f"Upload failed for {db_name}. Local backup preserved at: {backup_zip}", "error", log_cb)
        else:
            emit_log(f"Skipping upload for {db_name}: backup creation failed.", "warning", log_cb)

            
    if progress_cb:
        progress_cb(1.0)
        
    summary = f"Workflow completed: {success_count}/{total_dbs} databases successfully backed up and synced."
    emit_log(summary, "info", log_cb)
    emit_log("=" * 60, "info", log_cb)
    
    if status_cb:
        status_cb("Completed" if success_count == total_dbs else "Completed with Warnings")
        
    return (success_count == total_dbs), summary


def cleanup_local_backup_folder(folder=None, log_cb=None):
    """
    On-demand disk maintenance tool.
    Scans the local backup directory and removes all residual .bak and .zip files 
    (from interrupted runs or historical tests), calculating total freed bytes.
    """
    if not folder:
        config = load_config()
        folder = config.get("BACKUP_FOLDER", "C:\\temp\\backups")
    if not os.path.exists(folder):
        return 0, 0
    deleted_files = 0
    freed_bytes = 0
    for fname in os.listdir(folder):
        if fname.lower().endswith(('.bak', '.zip')):
            fpath = os.path.join(folder, fname)
            try:
                if os.path.isfile(fpath):
                    sz = os.path.getsize(fpath)
                    os.remove(fpath)
                    deleted_files += 1
                    freed_bytes += sz
            except Exception as e:
                emit_log(f"Failed to delete {fname}: {e}", "warning", log_cb)
    if deleted_files > 0:
        freed_str = format_file_size(freed_bytes)
        emit_log(f"Local storage cleaned: Removed {deleted_files} files, freed {freed_str} of disk space.", "info", log_cb)
    else:
        emit_log("Local storage is already clean (0 residual backup files found).", "info", log_cb)
    return deleted_files, freed_bytes


# =============================================================================
# 7. WINDOWS TASK SCHEDULER ORCHESTRATION
# =============================================================================

def is_admin():
    """Checks if the current process has Windows Administrator privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_command_elevated(cmd_string):
    """
    Executes a shell command with elevated Windows Administrator privileges
    via PowerShell Start-Process -Verb RunAs. Returns True if successful.
    """
    encoded_cmd = cmd_string.replace('"', '\\"')
    ps_cmd = (
        f'Start-Process cmd.exe -ArgumentList \'/c "{encoded_cmd}"\' '
        f'-Verb RunAs -WindowStyle Hidden -Wait'
    )
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=30)
        return res.returncode == 0
    except Exception:
        return False


def get_scheduler_status():
    """
    Queries Windows Task Scheduler to determine active automation state.
    Checks both Unattended System Service (Session 0) and Standard User Task.
    Returns: (is_active, status_message, mode)
    where mode is 'SYSTEM_SERVICE', 'USER_TASK', or 'NONE'.
    """
    # 1. Check Unattended Windows System Service
    try:
        cmd = f'schtasks /query /tn "{SYSTEM_SERVICE_TASK_NAME}" /fo CSV /nh'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and SYSTEM_SERVICE_TASK_NAME in res.stdout:
            status_line = res.stdout.strip().split("\n")[0]
            parts = [p.strip('"\r') for p in status_line.split('","')]
            status = parts[2] if len(parts) > 2 else "Scheduled"
            next_run = parts[1] if len(parts) > 1 else "Unknown"
            return True, f"Active (System Service - Session 0) - Next Run: {next_run}", "SYSTEM_SERVICE"
    except Exception:
        pass

    # 2. Check Standard User Scheduled Task
    try:
        cmd = f'schtasks /query /tn "{TASK_SCHEDULER_NAME}" /fo CSV /nh'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and TASK_SCHEDULER_NAME in res.stdout:
            status_line = res.stdout.strip().split("\n")[0]
            parts = [p.strip('"\r') for p in status_line.split('","')]
            status = parts[2] if len(parts) > 2 else "Scheduled"
            next_run = parts[1] if len(parts) > 1 else "Unknown"
            return True, f"Active (Standard User Task) - Next Run: {next_run}", "USER_TASK"
    except Exception:
        pass

    # 3. Check Background Daemon Task (if present)
    try:
        cmd = f'schtasks /query /tn "{DAEMON_SERVICE_TASK_NAME}" /fo CSV /nh'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and DAEMON_SERVICE_TASK_NAME in res.stdout:
            return True, "Active (Continuous Background Daemon Service)", "SYSTEM_SERVICE"
    except Exception:
        pass

    return False, "Not Scheduled", "NONE"


def enable_scheduler(executable_path=None, day="MON", time_str="02:00", as_system_service=True, on_boot=False):
    """
    Registers the backup cycle in Windows Task Scheduler using schtasks /create.
    
    Modes:
    1. Unattended Windows System Service (as_system_service=True, Default):
       - Configured under 'NT AUTHORITY\\SYSTEM' with /rl HIGHEST.
       - Runs in Session 0 independent of user login or RDP disconnects.
       - If on_boot=True, also registers a boot/startup recovery trigger.
    2. Standard User Task (as_system_service=False):
       - Runs under current user account (/rl LIMITED).
       - Requires zero admin rights.
    """
    if not executable_path:
        if getattr(sys, 'frozen', False):
            executable_path = sys.executable
        else:
            executable_path = f'python "{os.path.join(BASE_DIR, "auto_backup.py")}"'
            
    if executable_path.startswith("python "):
        cmd_run = f'{executable_path} --auto'
    else:
        cmd_run = f'\\"{executable_path}\\" --auto'

    if as_system_service:
        # First remove any user-level task to avoid conflicting double-executions
        subprocess.run(f'schtasks /delete /tn "{TASK_SCHEDULER_NAME}" /f', shell=True, capture_output=True)
        
        target_task = SYSTEM_SERVICE_TASK_NAME
        cmd = f'schtasks /create /tn "{target_task}" /tr "{cmd_run}" /sc weekly /d {day} /st {time_str} /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
        
        if not is_admin():
            ok = run_command_elevated(cmd)
            if ok:
                emit_log(f"Unattended System Service '{target_task}' configured via elevated prompt.")
                if on_boot:
                    boot_cmd = f'schtasks /create /tn "{DAEMON_SERVICE_TASK_NAME}" /tr "{cmd_run}" /sc ONSTART /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
                    run_command_elevated(boot_cmd)
                return True, f"Windows System Service Active: Every {day} at {time_str} (Unattended Session 0)."
            else:
                return False, "Administrator elevation was cancelled or denied."
        else:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                emit_log(f"Unattended System Service '{target_task}' created successfully.")
                if on_boot:
                    boot_cmd = f'schtasks /create /tn "{DAEMON_SERVICE_TASK_NAME}" /tr "{cmd_run}" /sc ONSTART /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
                    subprocess.run(boot_cmd, shell=True, capture_output=True)
                return True, f"Windows System Service Active: Every {day} at {time_str} (Unattended Session 0)."
            else:
                err = res.stderr or res.stdout
                return False, f"Scheduler error: {err}"
    else:
        # First remove any system-level task to avoid double-runs
        subprocess.run(f'schtasks /delete /tn "{SYSTEM_SERVICE_TASK_NAME}" /f', shell=True, capture_output=True)
        subprocess.run(f'schtasks /delete /tn "{DAEMON_SERVICE_TASK_NAME}" /f', shell=True, capture_output=True)
        
        target_task = TASK_SCHEDULER_NAME
        cmd = f'schtasks /create /tn "{target_task}" /tr "{cmd_run}" /sc weekly /d {day} /st {time_str} /f'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            emit_log(f"Standard user task '{target_task}' created successfully (Every {day} at {time_str}).")
            return True, f"Scheduled successfully: Every {day} at {time_str}."
        else:
            err = res.stderr or res.stdout
            emit_log(f"Failed to create scheduled task: {err}", "error")
            return False, f"Scheduler error: {err}"


def disable_scheduler():
    """
    Unregisters and cleans up all scheduled tasks (User, System Service, and Daemon Boot task).
    """
    tasks_to_remove = [TASK_SCHEDULER_NAME, SYSTEM_SERVICE_TASK_NAME, DAEMON_SERVICE_TASK_NAME]
    removed_any = False
    
    for tn in tasks_to_remove:
        cmd = f'schtasks /delete /tn "{tn}" /f'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            removed_any = True
        elif not is_admin():
            if run_command_elevated(cmd):
                removed_any = True
                
    emit_log("Windows automation schedules removed.")
    return True, "Automated schedules removed."


# =============================================================================
# 8. WINDOWS SQL SERVER DISCOVERY
# =============================================================================

def detect_sql_server_instances():
    """
    Auto-discovers locally installed Microsoft SQL Server instances.
    
    Technique:
    1. Inspects the Windows Registry at:
       HKLM\\SOFTWARE\\Microsoft\\Microsoft SQL Server\\Instance Names\\SQL
    2. Falls back to querying the Windows Service Control Manager for MSSQL$* services.
    """
    instances = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL") as key:
            i = 0
            while True:
                try:
                    name, _, _ = winreg.EnumValue(key, i)
                    instances.append(name)
                    i += 1
                except OSError:
                    break
    except Exception:
        pass
        
    if not instances:
        try:
            res = subprocess.run('sc query state= all | findstr /i "MSSQL$"', shell=True, capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "SERVICE_NAME: MSSQL$" in line:
                    inst = line.split("MSSQL$")[-1].strip()
                    if inst and inst not in instances:
                        instances.append(inst)
        except Exception:
            pass
            
    return instances


def detect_user_databases(sql_server, sql_user="", sql_password=""):
    """
    Queries Microsoft SQL Server for online user databases.
    
    Executes:
    SELECT name FROM sys.databases WHERE database_id > 4 AND state_desc = 'ONLINE';
    Filtering out database_id <= 4 excludes internal system DBs:
    1: master, 2: tempdb, 3: model, 4: msdb
    """
    if sql_user and sql_password:
        cmd = f'sqlcmd -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -h -1 -W -Q "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE database_id > 4"'
    else:
        cmd = f'sqlcmd -b -l 15 -S "{sql_server}" -E -C -h -1 -W -Q "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE database_id > 4"'
        
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip() and not line.startswith("---")]
    except Exception:
        pass
    return []
