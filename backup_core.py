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
import socket
import shutil
import platform
from datetime import datetime

# Global socket timeout to prevent WinError 10060 (WSAETIMEDOUT) on fluctuating client connections
try:
    socket.setdefaulttimeout(180)
except Exception:
    pass

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

# Initialize dedicated application logger with UTF-8 FileHandler
logger = logging.getLogger("DatabaseBackup")
logger.setLevel(logging.INFO)
logger.propagate = False
try:
    _fh = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(_fh)
except Exception:
    pass


def emit_log(message, level="info", log_cb=None):
    """
    Dual-dispatch logging utility.
    1. Persists the log record to the local backup_log.txt file on disk with instant flush.
    2. Prints the message to standard output for CLI sessions.
    3. Safely invokes the UI log callback (log_cb) if supplied by app_gui.py.
    """
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {message}"
    
    # Write to local file log based on severity
    if level == "critical":
        logger.critical(message)
    elif level == "error":
        logger.error(message)
    elif level == "warning":
        logger.warning(message)
    else:
        logger.info(message)
        
    # Flush file handlers immediately to ensure real-time disk persistence
    for h in logger.handlers:
        try:
            h.flush()
        except Exception:
            pass

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
        "SCHEDULE_DAYS": ["MON"],
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

def open_path_native(target_path):
    """
    Cross-platform helper to open a folder or file in the default OS file manager or application.
    Supports Windows (os.startfile), macOS ('open'), and Linux ('xdg-open').
    """
    if not os.path.exists(target_path):
        return False
    try:
        sys_plat = platform.system().lower()
        if "windows" in sys_plat:
            os.startfile(target_path)
        elif "darwin" in sys_plat:
            subprocess.Popen(["open", target_path])
        else:
            subprocess.Popen(["xdg-open", target_path])
        return True
    except Exception:
        return False


def grant_sql_folder_permissions(folder_path):
    """
    Grants filesystem write/modify permissions on the target directory.
    - On Windows: Uses icacls with language-independent SIDs (*S-1-1-0 Everyone, *S-1-5-32-545 Users).
    - On macOS / Linux: Ensures directory exists and applies readable/writable permissions.
    """
    try:
        norm_path = os.path.normpath(folder_path)
        if not os.path.exists(norm_path):
            os.makedirs(norm_path, exist_ok=True)
            
        if platform.system().lower() == "windows":
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
        else:
            try:
                os.chmod(norm_path, 0o775)
            except Exception:
                pass
    except Exception:
        pass


def find_sql_cli_executable():
    """
    Locates the most appropriate SQL command-line client on the host system.
    Supports modern ODBC 18/17/13/11 sqlcmd, SQL Server 2005-2022 sqlcmd,
    and legacy SQL Server 2000-2005 osql.exe across both 64-bit and 32-bit paths.
    
    Returns:
        (cli_type, cli_path) where cli_type is 'sqlcmd' or 'osql'.
    """
    # 1. Check if sqlcmd is directly available on system PATH
    found = shutil.which("sqlcmd")
    if found:
        return "sqlcmd", found

    # 2. Check well-known SQL Server installation paths
    program_dirs = []
    for env_var in ["ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"]:
        p = os.environ.get(env_var)
        if p and p not in program_dirs and os.path.exists(p):
            program_dirs.append(p)

    candidate_sqlcmd_subpaths = [
        r"Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\Client SDK\ODBC\130\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\Client SDK\ODBC\110\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\160\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\150\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\140\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\130\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\120\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\110\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\100\Tools\Binn\sqlcmd.exe",
        r"Microsoft SQL Server\90\Tools\Binn\sqlcmd.exe",
    ]

    for pdir in program_dirs:
        for subpath in candidate_sqlcmd_subpaths:
            full_path = os.path.join(pdir, subpath)
            if os.path.isfile(full_path):
                return "sqlcmd", full_path

    # 3. Fallback to osql.exe for older legacy systems (SQL Server 2000 / 2005)
    found_osql = shutil.which("osql")
    if found_osql:
        return "osql", found_osql

    candidate_osql_subpaths = [
        r"Microsoft SQL Server\80\Tools\Binn\osql.exe",
        r"Microsoft SQL Server\90\Tools\Binn\osql.exe",
        r"Microsoft SQL Server\100\Tools\Binn\osql.exe",
    ]
    for pdir in program_dirs:
        for subpath in candidate_osql_subpaths:
            full_path = os.path.join(pdir, subpath)
            if os.path.isfile(full_path):
                return "osql", full_path

    # Fallback to standard command name
    return "sqlcmd", "sqlcmd"


def execute_sql_query_adaptive(sql_server, query, sql_user="", sql_password="", timeout=15):
    """
    Executes a SQL query against SQL Server adaptively handling modern (-C) and legacy flags.
    Automatically retries without '-C' if the installed sqlcmd does not recognize the flag.
    Falls back to osql if sqlcmd is unavailable.
    
    Returns:
        (returncode, stdout, stderr)
    """
    cli_type, cli_path = find_sql_cli_executable()
    escaped_query = query.replace('"', '""')
    
    if cli_type == "sqlcmd":
        # First attempt: Try with -C (Trust Server Certificate, required for modern ODBC 18)
        if sql_user and sql_password:
            cmd = f'"{cli_path}" -b -l {timeout} -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -h -1 -W -Q "{escaped_query}"'
        else:
            cmd = f'"{cli_path}" -b -l {timeout} -S "{sql_server}" -E -C -h -1 -W -Q "{escaped_query}"'
            
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout + 5)
            # Check if -C was rejected as an unknown/invalid option (common on older SQL Server / SSMS versions)
            err_lower = (res.stderr or "").lower() + (res.stdout or "").lower()
            if "-c" in err_lower and ("unknown option" in err_lower or "invalid option" in err_lower or "unrecognized" in err_lower):
                # Fallback attempt without -C
                if sql_user and sql_password:
                    cmd_no_c = f'"{cli_path}" -b -l {timeout} -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -h -1 -W -Q "{escaped_query}"'
                else:
                    cmd_no_c = f'"{cli_path}" -b -l {timeout} -S "{sql_server}" -E -h -1 -W -Q "{escaped_query}"'
                res = subprocess.run(cmd_no_c, shell=True, capture_output=True, text=True, timeout=timeout + 5)
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return -1, "", str(e)
            
    else:  # osql.exe fallback
        if sql_user and sql_password:
            cmd = f'"{cli_path}" -b -l {timeout} -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -n -h -1 -w 8000 -Q "{escaped_query}"'
        else:
            cmd = f'"{cli_path}" -b -l {timeout} -S "{sql_server}" -E -n -h -1 -w 8000 -Q "{escaped_query}"'
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout + 5)
            return res.returncode, res.stdout, res.stderr
        except Exception as e:
            return -1, "", str(e)


def execute_sql_backup_command(sql_server, db_name, bak_filepath, sql_user="", sql_password="", cancel_check=None):
    """
    Executes BACKUP DATABASE command adaptively handling modern and legacy SQL Server / SSMS versions.
    Integrates with backup_controller for instant emergency abort.
    """
    cli_type, cli_path = find_sql_cli_executable()
    backup_sql = f"BACKUP DATABASE [{db_name}] TO DISK='{bak_filepath}' WITH FORMAT"
    
    def _run_cmd(cmd_str):
        proc = subprocess.Popen(cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        backup_controller.set_active_process(proc)
        try:
            stdout, stderr = proc.communicate()
            return proc.returncode, stdout, stderr
        finally:
            backup_controller.clear_active_process()

    if cli_type == "sqlcmd":
        # Try with -C first
        if sql_user and sql_password:
            cmd = f'"{cli_path}" -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -Q "{backup_sql}"'
        else:
            cmd = f'"{cli_path}" -b -l 15 -S "{sql_server}" -E -C -Q "{backup_sql}"'
            
        code, out, err = _run_cmd(cmd)
        combined_err = ((err or "") + "\n" + (out or "")).lower()
        if "-c" in combined_err and ("unknown option" in combined_err or "invalid option" in combined_err or "unrecognized" in combined_err):
            # Retry without -C
            if sql_user and sql_password:
                cmd_no_c = f'"{cli_path}" -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -Q "{backup_sql}"'
            else:
                cmd_no_c = f'"{cli_path}" -b -l 15 -S "{sql_server}" -E -Q "{backup_sql}"'
            code, out, err = _run_cmd(cmd_no_c)
        return code, out, err
    else:
        # osql.exe fallback
        if sql_user and sql_password:
            cmd = f'"{cli_path}" -b -l 15 -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -n -Q "{backup_sql}"'
        else:
            cmd = f'"{cli_path}" -b -l 15 -S "{sql_server}" -E -n -Q "{backup_sql}"'
        return _run_cmd(cmd)


def get_sql_instance_default_backup_path(sql_server, sql_user="", sql_password=""):
    """
    Queries SQL Server instance for its default backup directory,
    which is guaranteed to have write permissions for the SQL Server engine service.
    Works adaptively across modern and legacy SQL Server / SSMS installations.
    """
    query = "SET NOCOUNT ON; SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS VARCHAR(500))"
    retcode, stdout, _ = execute_sql_query_adaptive(sql_server, query, sql_user, sql_password, timeout=15)
    if retcode == 0 and stdout.strip():
        lines = [line.strip() for line in stdout.strip().splitlines() if line.strip() and not line.strip().startswith("-")]
        if lines:
            candidate = os.path.normpath(lines[0])
            if os.path.isdir(candidate):
                return candidate
    return None


def generate_and_compress_backup(folder, db_name, sql_server, sql_user="", sql_password="", log_cb=None, status_cb=None, cancel_check=None):
    """
    Executes native Microsoft SQL Server database backup and Level 9 Deflate compression.
    
    Resilience, Failover & Emergency Cancellation Features:
    1. Normalizes all folder and file paths to standard OS path separators.
    2. Proactively configures filesystem permissions on the destination directory.
    3. Traps SQL Server Error 5 (Operating system error 5: Access is denied) and Msg 3201:
       If the SQL Server service account lacks rights to write to user-space folders
       (e.g., Desktop or Documents), it automatically queries SQL Server's internal 
       InstanceDefaultBackupPath, runs the backup to that authorized location,
       compresses the archive directly into the user's requested destination, and purges
       the temporary .bak from the SQL Server directory.
    4. Adaptive SQL Driver Detection: Works seamlessly with modern ODBC 18 sqlcmd (-C),
       legacy sqlcmd (without -C), and legacy osql.exe for older SQL Server / SSMS setups.
    5. Emergency Abort & Cleanup:
       Monitors backup_controller and cancel_check. If aborted, terminates the running
       SQL child process immediately, halts compression, and deletes any partial
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

    try:
        # Execute database backup adaptively with emergency termination support
        returncode, stdout, stderr = execute_sql_backup_command(
            sql_server=sql_server,
            db_name=db_name,
            bak_filepath=bak_filepath,
            sql_user=sql_user,
            sql_password=sql_password,
            cancel_check=cancel_check
        )

        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
            emit_log(f"SQL Backup for {db_name} aborted by user. Purging temporary files...", "warning", log_cb)
            if os.path.exists(bak_filepath):
                try:
                    os.remove(bak_filepath)
                except Exception:
                    pass
            return None

        backup_succeeded = (returncode == 0 and os.path.exists(bak_filepath))

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
                    fallback_folder = os.path.normpath("C:\\temp\\backups") if platform.system().lower() == "windows" else "/tmp/backups"
                    os.makedirs(fallback_folder, exist_ok=True)
                    grant_sql_folder_permissions(fallback_folder)
                    
                emit_log(f"Failing over to SQL-authorized directory: {fallback_folder}", "info", log_cb)
                fallback_bak = os.path.normpath(os.path.join(fallback_folder, bak_filename))
                
                rc_fb, out_fb, err_fb = execute_sql_backup_command(
                    sql_server=sql_server,
                    db_name=db_name,
                    bak_filepath=fallback_bak,
                    sql_user=sql_user,
                    sql_password=sql_password,
                    cancel_check=cancel_check
                )

                if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                    emit_log(f"SQL Failover Backup for {db_name} aborted by user. Purging temporary files...", "warning", log_cb)
                    if os.path.exists(fallback_bak):
                        try:
                            os.remove(fallback_bak)
                        except Exception:
                            pass
                    return None

                if rc_fb == 0 and os.path.exists(fallback_bak):
                    emit_log(f"Failover SQL backup successfully created at: {fallback_bak}", "info", log_cb)
                    bak_filepath = fallback_bak
                    backup_succeeded = True
                else:
                    err_details = ((err_fb or "") + "\n" + (out_fb or "")).strip()
                    emit_log(f"SQL Backup failed even on failover location: {err_details}", "error", log_cb)
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

def upload_to_google_drive(creds, file_path, folder_id, retries=3, log_cb=None, status_cb=None, progress_cb=None, telemetry_cb=None, cancel_check=None):
    """
    Streams a local backup archive to the configured Google Drive folder.
    
    Enterprise Network Resilience & In-Chunk Auto-Resume:
    - Uses resumable chunked upload with 1MB chunksize for maximum reliability on slow/erratic broadband.
    - If a connection drops (WinError 10060, WSAETIMEDOUT, ConnectionResetError, BrokenPipeError, or HTTP 5xx),
      the inner chunk retry loop retries request.next_chunk() up to 10 times with exponential backoff.
    - Google's MediaFileUpload queries the active resumable URI and RESUMES from the exact byte where it paused,
      guaranteeing zero byte loss and never restarting a 500MB+ file from 0%.
    - Real-time Telemetry: Live speed, percentage, transferred bytes, and ETA.
    - Emergency stop awareness: monitors backup_controller and cancel_check to instantly abort upload.
    - Traps Google Drive quota exhaustion errors (HTTP 403 storageQuotaExceeded).
    """
    file_name = os.path.basename(file_path)
    try:
        total_file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    except Exception:
        total_file_size = 0

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
            emit_log(f"Uploading {file_name} to Google Drive ({format_file_size(total_file_size)}, Session {attempt}/{retries})...", "info", log_cb)
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            # Stream in 1MB chunks: optimal balance for slow connections (100-200 KB/s) to avoid socket timeout limits
            media = MediaFileUpload(file_path, chunksize=1 * 1024 * 1024, resumable=True)
            request = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            )
            
            uploaded_file = None
            upload_start_time = time.time()
            last_logged_time = upload_start_time
            last_logged_pct = 0.0
            last_bytes_done = 0

            while uploaded_file is None:
                if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                    emit_log(f"Upload of {file_name} aborted by user during transfer.", "warning", log_cb)
                    return None

                # In-chunk retry loop with exponential backoff on transient network interruptions
                chunk_status = None
                max_chunk_retries = 10
                for chunk_attempt in range(1, max_chunk_retries + 1):
                    if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                        emit_log(f"Upload of {file_name} cancelled during transfer.", "warning", log_cb)
                        return None
                    try:
                        chunk_status, uploaded_file = request.next_chunk()
                        break  # Chunk transferred successfully!
                    except Exception as chunk_err:
                        if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                            return None
                        
                        is_quota_err = isinstance(chunk_err, HttpError) and chunk_err.resp.status in [400, 403] and 'quota' in str(chunk_err).lower()
                        if is_quota_err:
                            emit_log(f"CRITICAL: Google Drive storage quota full! {chunk_err}", "critical", log_cb)
                            return None

                        # Check for recoverable network / timeout / socket glitches
                        resumed_byte = last_bytes_done
                        if chunk_status:
                            resumed_byte = chunk_status.resumable_progress
                        
                        chunk_delay = min(60, 2 ** min(chunk_attempt, 6))
                        err_str = f"{type(chunk_err).__name__}: {chunk_err}"
                        emit_log(
                            f"Transient network glitch during upload ({err_str}). "
                            f"Auto-resuming chunk from byte {format_file_size(resumed_byte)} in {chunk_delay}s "
                            f"(Chunk Retry {chunk_attempt}/{max_chunk_retries})...",
                            "warning",
                            log_cb
                        )
                        if status_cb:
                            status_cb(f"Connection paused. Resuming from {format_file_size(resumed_byte)} in {chunk_delay}s...")
                        
                        # Sleep in 0.5s increments with emergency stop checks
                        for _ in range(int(chunk_delay * 2)):
                            if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                                return None
                            time.sleep(0.5)
                else:
                    # All 10 in-chunk retries exhausted for this session
                    raise IOError(f"Network connection lost after {max_chunk_retries} continuous resume retries.")

                status = chunk_status
                now = time.time()
                elapsed = max(0.001, now - upload_start_time)

                if status:
                    bytes_done = status.resumable_progress
                    last_bytes_done = bytes_done
                    total_bytes = status.total_size or total_file_size or 1
                    fraction = min(1.0, max(0.0, float(status.progress() if status.progress() is not None else (bytes_done / total_bytes))))
                    pct = fraction * 100.0
                    
                    # Compute transfer speed and ETA
                    speed_bps = (bytes_done / elapsed) if (elapsed > 0.1 and bytes_done > 0) else 0.0
                    if speed_bps > 0:
                        speed_str = f"{format_file_size(speed_bps)}/s"
                        remaining_bytes = max(0, total_bytes - bytes_done)
                        eta_seconds = int(remaining_bytes / speed_bps)
                        if eta_seconds < 60:
                            eta_str = f"{eta_seconds}s"
                        elif eta_seconds < 3600:
                            eta_str = f"{eta_seconds // 60}m {eta_seconds % 60:02d}s"
                        else:
                            eta_str = f"{eta_seconds // 3600}h {(eta_seconds % 3600) // 60}m"
                    else:
                        speed_str = "Calculating..."
                        eta_str = "--"

                    uploaded_str = format_file_size(bytes_done)
                    total_str = format_file_size(total_bytes)
                    
                    status_text = f"Uploading {file_name}: {pct:.1f}% ({uploaded_str} / {total_str}) • {speed_str} • ETA: {eta_str}"
                    if status_cb:
                        status_cb(status_text)
                    if progress_cb:
                        progress_cb(fraction)
                    if telemetry_cb:
                        try:
                            telemetry_cb({
                                "file_name": file_name,
                                "bytes_done": bytes_done,
                                "total_bytes": total_bytes,
                                "percent": pct,
                                "fraction": fraction,
                                "speed_bps": speed_bps,
                                "speed_str": speed_str,
                                "eta_str": eta_str,
                                "elapsed": elapsed
                            })
                        except Exception:
                            pass

                    # Periodic log emission (every ~4 seconds or every 25% advancement)
                    if (now - last_logged_time >= 4.0) or (pct - last_logged_pct >= 25.0):
                        emit_log(f"Upload progress: {pct:.1f}% ({uploaded_str} / {total_str}) | Speed: {speed_str} | ETA: {eta_str}", "info", log_cb)
                        last_logged_time = now
                        last_logged_pct = pct

            total_elapsed = max(0.001, time.time() - upload_start_time)
            final_size = total_file_size or (os.path.getsize(file_path) if os.path.exists(file_path) else 0)
            avg_speed_bps = (final_size / total_elapsed) if total_elapsed > 0 else 0.0
            avg_speed_str = f"{format_file_size(avg_speed_bps)}/s"

            if progress_cb:
                progress_cb(1.0)
            if status_cb:
                status_cb(f"Uploaded {file_name} (100%) in {total_elapsed:.1f}s @ {avg_speed_str}")
            if telemetry_cb:
                try:
                    telemetry_cb({
                        "file_name": file_name,
                        "bytes_done": final_size,
                        "total_bytes": final_size,
                        "percent": 100.0,
                        "fraction": 1.0,
                        "speed_bps": avg_speed_bps,
                        "speed_str": avg_speed_str,
                        "eta_str": "0s",
                        "elapsed": total_elapsed
                    })
                except Exception:
                    pass

            file_id = uploaded_file.get('id')
            link = uploaded_file.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            if link:
                emit_log(f"Upload complete for {file_name}! (Transferred in {total_elapsed:.1f}s @ {avg_speed_str}) Link: {link}", "info", log_cb)
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
            emit_log("Retrying upload session in 10 seconds...", "info", log_cb)
            for _ in range(20):
                if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                    return None
                time.sleep(0.5)
            
    emit_log(f"Upload failed after {retries} session attempts for {file_name}.", "critical", log_cb)
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

def run_full_backup(config=None, log_cb=None, progress_cb=None, status_cb=None, cancel_check=None, telemetry_cb=None):
    """
    Master end-to-end backup orchestrator.
    
    Coordinates the entire backup pipeline for all databases defined in TARGET_DATABASES:
    1. Resets cancellation controller and authenticates Google OAuth 2.0.
    2. Iterates sequentially across target databases with active cancellation guards.
    3. Triggers native SQL extraction and Level 9 Deflate compression.
    4. Streams archive to Google Drive with 2MB chunked progress, real-time speed, & emergency abort.
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

        db_weight = 0.80 / max(1, total_dbs)
        db_base = 0.15 + (idx / max(1, total_dbs)) * 0.80
        if progress_cb:
            progress_cb(db_base)
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
            
            # Step 2: Stream archive to Google Drive with smooth real-time progress bridge
            if status_cb:
                status_cb(f"Uploading {file_name} ({file_size_str}) to Google Drive...")

            def _upload_progress_bridge(upload_fraction):
                if progress_cb:
                    # Compression takes 30% of this DB's phase, upload takes 70%
                    overall = db_base + (0.30 * db_weight) + (upload_fraction * 0.70 * db_weight)
                    progress_cb(min(0.98, max(0.0, overall)))

            link = upload_to_google_drive(
                creds=creds,
                file_path=backup_zip,
                folder_id=config.get("GOOGLE_DRIVE_FOLDER_ID"),
                retries=3,
                log_cb=log_cb,
                status_cb=status_cb,
                progress_cb=_upload_progress_bridge,
                telemetry_cb=telemetry_cb,
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
    Queries the host OS scheduler to determine active automation state.
    - On macOS: Checks LaunchAgents (~/Library/LaunchAgents/com.databasebackup.automation.plist).
    - On Windows: Checks Windows Task Scheduler for Unattended System Service (Session 0) and Standard User Task.
    Returns: (is_active, status_message, mode)
    where mode is 'SYSTEM_SERVICE', 'USER_TASK', or 'NONE'.
    """
    # 0. macOS LaunchAgent check
    if platform.system().lower() == "darwin":
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.databasebackup.automation.plist")
        if os.path.exists(plist_path):
            try:
                res = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5)
                if "com.databasebackup.automation" in res.stdout:
                    return True, "Active (macOS LaunchAgent Background Daemon)", "SYSTEM_SERVICE"
                return True, "Active (macOS LaunchAgent Plist Installed)", "SYSTEM_SERVICE"
            except Exception:
                return True, "Active (macOS LaunchAgent)", "SYSTEM_SERVICE"
        return False, "Not Scheduled", "NONE"

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


def enable_scheduler(executable_path=None, days="MON", time_str="02:00", as_system_service=True, on_boot=False):
    """
    Registers the backup cycle in the OS automation scheduler.
    - On macOS: Configures and loads LaunchAgent in ~/Library/LaunchAgents/
    - On Windows: Registers in Windows Task Scheduler via schtasks /create
    
    Supports:
    - Any single day (e.g. 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN')
    - Multiple days (e.g. ['MON', 'WED', 'FRI'] or 'MON,WED,FRI')
    - Daily execution (['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'] or 'DAILY')
    - Any time in 24-hour format (e.g. '02:00', '14:30', '23:00')
    """
    if not executable_path:
        if getattr(sys, 'frozen', False):
            executable_path = sys.executable
        else:
            executable_path = f'python "{os.path.join(BASE_DIR, "auto_backup.py")}"'

    # Normalize days input
    if isinstance(days, str):
        if "," in days:
            days_list = [d.strip().upper() for d in days.split(",") if d.strip()]
        else:
            days_list = [days.strip().upper()]
    elif isinstance(days, (list, tuple, set)):
        days_list = [str(d).strip().upper() for d in days if str(d).strip()]
    else:
        days_list = ["MON"]

    all_days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    is_daily = ("DAILY" in days_list or "ALL" in days_list or "*" in days_list or set(days_list) == set(all_days))

    day_names_map = {
        "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
        "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"
    }

    ordered_days = [d for d in all_days if d in days_list]
    if not ordered_days:
        ordered_days = ["MON"]
        
    if is_daily:
        friendly_schedule = f"Every Day at {time_str}"
    else:
        friendly_days = [day_names_map.get(d, d) for d in ordered_days]
        if len(friendly_days) == 1:
            friendly_schedule = f"Every {friendly_days[0]} at {time_str}"
        elif len(friendly_days) == 2:
            friendly_schedule = f"Every {friendly_days[0]} and {friendly_days[1]} at {time_str}"
        else:
            friendly_schedule = f"Every {', '.join(friendly_days[:-1])}, and {friendly_days[-1]} at {time_str}"

    # macOS LaunchAgent Implementation
    if platform.system().lower() == "darwin":
        plist_dir = os.path.expanduser("~/Library/LaunchAgents")
        os.makedirs(plist_dir, exist_ok=True)
        plist_path = os.path.join(plist_dir, "com.databasebackup.automation.plist")
        
        try:
            hour_val, min_val = [int(p) for p in time_str.split(":")[:2]]
        except Exception:
            hour_val, min_val = 2, 0
            
        weekday_map = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
        calendar_intervals = []
        if is_daily:
            calendar_intervals.append(f"            <dict>\n                <key>Hour</key>\n                <integer>{hour_val}</integer>\n                <key>Minute</key>\n                <integer>{min_val}</integer>\n            </dict>")
        else:
            for d in ordered_days:
                w_num = weekday_map.get(d, 1)
                calendar_intervals.append(f"            <dict>\n                <key>Weekday</key>\n                <integer>{w_num}</integer>\n                <key>Hour</key>\n                <integer>{hour_val}</integer>\n                <key>Minute</key>\n                <integer>{min_val}</integer>\n            </dict>")
                
        intervals_str = "\n".join(calendar_intervals)
        
        if getattr(sys, 'frozen', False):
            exec_args = f"        <string>{sys.executable}</string>\n        <string>--auto</string>"
        else:
            python_bin = sys.executable or "python3"
            script_file = os.path.join(BASE_DIR, "auto_backup.py")
            exec_args = f"        <string>{python_bin}</string>\n        <string>{script_file}</string>\n        <string>--auto</string>"

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.databasebackup.automation</string>
    <key>ProgramArguments</key>
    <array>
{exec_args}
    </array>
    <key>StartCalendarInterval</key>
    <array>
{intervals_str}
    </array>
    <key>RunAtLoad</key>
    <{'true' if on_boot else 'false'}/>
    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>
</dict>
</plist>
"""
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(plist_content)
            
        try:
            subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
            subprocess.run(["launchctl", "load", plist_path], capture_output=True)
        except Exception:
            pass
            
        emit_log(f"macOS LaunchAgent registered ({friendly_schedule}) at: {plist_path}")
        return True, f"macOS LaunchAgent Active: {friendly_schedule}"

    # Windows Task Scheduler Implementation
    if executable_path.startswith("python "):
        cmd_run = f'{executable_path} --auto'
    else:
        cmd_run = f'\\"{executable_path}\\" --auto'

    if is_daily:
        schedule_args = f'/sc daily /st {time_str}'
    else:
        days_csv = ",".join(ordered_days)
        schedule_args = f'/sc weekly /d {days_csv} /st {time_str}'

    if as_system_service:
        # First remove any user-level task to avoid conflicting double-executions
        subprocess.run(f'schtasks /delete /tn "{TASK_SCHEDULER_NAME}" /f', shell=True, capture_output=True)
        
        target_task = SYSTEM_SERVICE_TASK_NAME
        cmd = f'schtasks /create /tn "{target_task}" /tr "{cmd_run}" {schedule_args} /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
        
        if not is_admin():
            ok = run_command_elevated(cmd)
            if ok:
                emit_log(f"Unattended System Service '{target_task}' configured via elevated prompt.")
                if on_boot:
                    boot_cmd = f'schtasks /create /tn "{DAEMON_SERVICE_TASK_NAME}" /tr "{cmd_run}" /sc ONSTART /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
                    run_command_elevated(boot_cmd)
                return True, f"Windows System Service Active: {friendly_schedule} (Unattended Session 0)."
            else:
                return False, "Administrator elevation was cancelled or denied."
        else:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                emit_log(f"Unattended System Service '{target_task}' created successfully.")
                if on_boot:
                    boot_cmd = f'schtasks /create /tn "{DAEMON_SERVICE_TASK_NAME}" /tr "{cmd_run}" /sc ONSTART /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
                    subprocess.run(boot_cmd, shell=True, capture_output=True)
                return True, f"Windows System Service Active: {friendly_schedule} (Unattended Session 0)."
            else:
                err = res.stderr or res.stdout
                return False, f"Scheduler error: {err}"
    else:
        # First remove any system-level task to avoid double-runs
        subprocess.run(f'schtasks /delete /tn "{SYSTEM_SERVICE_TASK_NAME}" /f', shell=True, capture_output=True)
        subprocess.run(f'schtasks /delete /tn "{DAEMON_SERVICE_TASK_NAME}" /f', shell=True, capture_output=True)
        
        target_task = TASK_SCHEDULER_NAME
        cmd = f'schtasks /create /tn "{target_task}" /tr "{cmd_run}" {schedule_args} /f'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            emit_log(f"Standard user task '{target_task}' created successfully ({friendly_schedule}).")
            return True, f"Scheduled successfully: {friendly_schedule}."
        else:
            err = res.stderr or res.stdout
            emit_log(f"Failed to create scheduled task: {err}", "error")
            return False, f"Scheduler error: {err}"


def disable_scheduler():
    """
    Unregisters and cleans up all scheduled tasks (User, System Service, Daemon Boot task, macOS LaunchAgents).
    """
    if platform.system().lower() == "darwin":
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.databasebackup.automation.plist")
        if os.path.exists(plist_path):
            try:
                subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
            except Exception:
                pass
            try:
                os.remove(plist_path)
            except Exception:
                pass
        emit_log("macOS LaunchAgent automation removed.")
        return True, "Automated schedules removed."

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
    Universal compatibility query across SQL Server 2000, 2005, 2008, 2008 R2, 2012, 2014, 2016, 2017, 2019, 2022:
    - Queries sys.databases on SQL Server 2005+
    - Falls back to master.dbo.sysdatabases on SQL Server 2000 / legacy setups
    - Excludes system databases (database_id / dbid <= 4: master, tempdb, model, msdb)
    """
    query = (
        "SET NOCOUNT ON; "
        "IF OBJECT_ID('sys.databases') IS NOT NULL "
        "  SELECT name FROM sys.databases WHERE database_id > 4 AND state_desc = 'ONLINE' "
        "ELSE "
        "  SELECT name FROM master.dbo.sysdatabases WHERE dbid > 4;"
    )
    rc, stdout, stderr = execute_sql_query_adaptive(sql_server, query, sql_user, sql_password, timeout=15)
    if rc == 0 and stdout.strip():
        lines = []
        for line in stdout.strip().splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("-") and not line_str.startswith("(") and not line_str.lower().startswith("name"):
                lines.append(line_str)
        return lines
    return []
