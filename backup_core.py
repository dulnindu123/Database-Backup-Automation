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
import re
import requests
from crypto_stream import encrypt_file
from broker_client import secure_upload

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
# SECURE BUILD: the app no longer requests Drive access at all. Uploads go through the broker.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]

from version import DEFAULT_TASK_NAME, PROGRAM_DATA_DIR

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = PROGRAM_DATA_DIR
LOG_FILE = os.path.join(DATA_DIR, "backup_log.txt")

# Standard Windows Task Scheduler & Service entry identifiers (Round 9 Requirement 3: Single Constant)
TASK_SCHEDULER_NAME = DEFAULT_TASK_NAME
SYSTEM_SERVICE_TASK_NAME = DEFAULT_TASK_NAME
DAEMON_SERVICE_TASK_NAME = DEFAULT_TASK_NAME



# =============================================================================
# SECURE BUILD HELPERS (input validation, broker readiness, hardened ACLs)
# =============================================================================
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-\. ]{0,127}$")
_CREATE_NO_WINDOW = 0x08000000 if platform.system().lower() == "windows" else 0


def _valid_db_name(db_name):
    return bool(db_name) and bool(_DB_NAME_RE.match(db_name))


# Export alias for public API / tests
is_safe_db_name = _valid_db_name


def broker_ready(config, base_dir=None):
    """Checks the prerequisites for a secure upload. Returns (ok, reason)."""
    b_dir = base_dir or BASE_DIR
    if not config.get("BROKER_URL"):
        return False, "BROKER_URL missing in config.json"

    token_file = config.get("BROKER_TOKEN_FILE", "token.dpapi")
    token_path = token_file if os.path.isabs(token_file) else os.path.join(b_dir, token_file)
    if not os.path.exists(token_path):
        if base_dir is None:
            data_dir = globals().get("DATA_DIR", b_dir)
            alt_path = os.path.join(data_dir, os.path.basename(token_file))
            if os.path.exists(alt_path):
                token_path = alt_path
            else:
                return False, f"{os.path.basename(token_file)} missing (provision this PC's token)"
        else:
            return False, f"{os.path.basename(token_file)} missing (provision this PC's token)"

    pub_file = config.get("PUBLIC_KEY_FILE", "backup_public.pem")
    pub_path = pub_file if os.path.isabs(pub_file) else os.path.join(b_dir, pub_file)
    if not os.path.exists(pub_path):
        if base_dir is None:
            data_dir = globals().get("DATA_DIR", b_dir)
            alt_pub = os.path.join(data_dir, os.path.basename(pub_file))
            if os.path.exists(alt_pub):
                pub_path = alt_pub
            else:
                return False, f"{os.path.basename(pub_file)} missing (encryption public key)"
        else:
            return False, f"{os.path.basename(pub_file)} missing (encryption public key)"

    if not config.get("ALLOW_NO_ESCROW", False):
        escrow_file = config.get("ESCROW_KEY_FILE", "escrow_public.pem")
        escrow_path = escrow_file if os.path.isabs(escrow_file) else os.path.join(b_dir, escrow_file)
        if not os.path.exists(escrow_path):
            if base_dir is None:
                data_dir = globals().get("DATA_DIR", b_dir)
                alt_escrow = os.path.join(data_dir, os.path.basename(escrow_file))
                if not os.path.exists(alt_escrow):
                    return False, f"{os.path.basename(escrow_file)} missing (escrow key required unless ALLOW_NO_ESCROW=true)"
            else:
                return False, f"{os.path.basename(escrow_file)} missing (escrow key required unless ALLOW_NO_ESCROW=true)"

    return True, ""


# Export alias
is_broker_ready = broker_ready


def _sql_service_account(sql_server):
    """'host\\INSTANCE' -> 'NT SERVICE\\MSSQL$INSTANCE'; default instance -> 'NT SERVICE\\MSSQLSERVER'."""
    inst = sql_server.split("\\", 1)[1].strip() if "\\" in (sql_server or "") else ""
    return "NT SERVICE\\MSSQL$" + inst if inst and inst.upper() != "MSSQLSERVER" else "NT SERVICE\\MSSQLSERVER"


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


def get_data_dir():
    """
    Returns system data directory: %ALLUSERSPROFILE%\\DatabaseBackupApp (C:\\ProgramData\\DatabaseBackupApp).
    Falls back to BASE_DIR if ProgramData is unavailable or if config exists in BASE_DIR.
    """
    program_data = os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData")
    target = os.path.join(program_data, "DatabaseBackupApp")
    if os.path.exists(target):
        return target
    if os.path.exists(os.path.join(BASE_DIR, "config.json")):
        return BASE_DIR
    try:
        os.makedirs(target, exist_ok=True)
        return target
    except Exception:
        return BASE_DIR


DATA_DIR = get_data_dir()
LOG_FILE = os.path.join(DATA_DIR, "backup_log.txt")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
if not os.path.exists(CONFIG_FILE) and os.path.exists(os.path.join(BASE_DIR, "config.json")):
    CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
    LOG_FILE = os.path.join(BASE_DIR, "backup_log.txt")
TOKEN_FILE = os.path.join(DATA_DIR, "token.dpapi")
if not os.path.exists(TOKEN_FILE) and os.path.exists(os.path.join(BASE_DIR, "token.dpapi")):
    TOKEN_FILE = os.path.join(BASE_DIR, "token.dpapi")

# Default Worksheet Tabs for Customer Master Google Sheet
DEFAULT_SHEET_TABS = {
    "BACKUP": "Backup Automation",
    "CLEANUP": "Server Cleanup"
}


def extract_google_id(url_or_id):
    """
    Extracts a clean Google Drive folder ID or Google Spreadsheet ID from either
    a full Google URL or a raw alphanumeric ID string.
    """
    if not url_or_id:
        return ""
    s = str(url_or_id).strip()
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', s)
    if m:
        return m.group(1)
    m = re.search(r'/folders/([a-zA-Z0-9_-]+)', s)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', s)
    if m:
        return m.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{15,}$', s):
        return s
    return s


def build_google_drive_url(folder_id_or_url):
    """Returns a direct browser link to the customer's Google Drive folder."""
    clean_id = extract_google_id(folder_id_or_url)
    if clean_id and clean_id.startswith("http"):
        return clean_id
    return f"https://drive.google.com/drive/folders/{clean_id}" if clean_id else ""


def build_google_sheet_url(sheet_id_or_url):
    """Returns a direct browser link to the customer's master Google Sheet."""
    clean_id = extract_google_id(sheet_id_or_url)
    if clean_id and clean_id.startswith("http"):
        return clean_id
    return f"https://docs.google.com/spreadsheets/d/{clean_id}/edit" if clean_id else ""


def consolidate_historical_logs(data_dir=None, base_dir=None):
    """
    Enforces the single-file logging policy:
    1. Scans DATA_DIR and BASE_DIR for legacy, rotating, or split log files.
    2. Sequentially merges unique historical entries into the single primary LOG_FILE (backup_log.txt).
    3. Safely removes redundant legacy log files so strictly one file is maintained.
    """
    d_dir = data_dir or DATA_DIR
    b_dir = base_dir or BASE_DIR
    primary_log = LOG_FILE
    
    candidate_dirs = list({d_dir, b_dir})
    legacy_files = []
    
    for c_dir in candidate_dirs:
        if not os.path.exists(c_dir):
            continue
        try:
            for entry in os.listdir(c_dir):
                full_path = os.path.join(c_dir, entry)
                if not os.path.isfile(full_path):
                    continue
                if os.path.abspath(full_path).lower() == os.path.abspath(primary_log).lower():
                    continue
                lower = entry.lower()
                if (lower.endswith(".log") or 
                    (lower.startswith("backup_log") and lower.endswith(".txt")) or 
                    lower.startswith("temp_log") or
                    lower.startswith("audit_log")):
                    legacy_files.append(full_path)
        except Exception:
            pass

    if not legacy_files:
        return

    existing_lines = set()
    if os.path.exists(primary_log):
        try:
            with open(primary_log, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        existing_lines.add(s)
        except Exception:
            pass

    merged_count = 0
    try:
        with open(primary_log, "a", encoding="utf-8", errors="replace") as out_f:
            for leg_path in sorted(legacy_files, key=lambda p: os.path.getmtime(p)):
                try:
                    with open(leg_path, "r", encoding="utf-8", errors="ignore") as in_f:
                        for line in in_f:
                            s = line.strip()
                            if s and s not in existing_lines:
                                out_f.write(line if line.endswith("\n") else line + "\n")
                                existing_lines.add(s)
                                merged_count += 1
                    os.remove(leg_path)
                except Exception:
                    pass
        if merged_count > 0:
            print(f"[SYSTEM] Consolidated {merged_count} historical log entries into single log file: {primary_log}")
    except Exception:
        pass


# Run historical log consolidation on startup
consolidate_historical_logs(DATA_DIR, BASE_DIR)

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


def redact_sensitive_tokens(text: str) -> str:
    """Masks authentication token secrets: pc-abc.12345678... -> pc-abc.[SEALED_SECRET]"""
    if not isinstance(text, str):
        return text
    return re.sub(r"\b(pc-[a-zA-Z0-9_-]+)\.[a-fA-F0-9]{16,}\b", r"\1.[SEALED_SECRET]", text)


def emit_log(message, level="info", log_cb=None, module=None):
    """
    Unified dual-dispatch logging utility for all modules.
    1. Persists the log record to the single local backup_log.txt file on disk with instant flush.
    2. Standardizes module tag ([BACKUP], [CLEANUP], [SYSTEM]).
    3. Prints the message to standard output for CLI sessions.
    4. Safely invokes the UI log callback (log_cb) if supplied by app_gui.py.
    5. Automatically redacts machine authentication tokens to prevent secret leakage.
    """
    message = redact_sensitive_tokens(str(message))
    mod_tag = f"[{module.upper()}] " if module else ""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] {mod_tag}{message}"
    
    log_msg = f"{mod_tag}{message}"
    # Write to local file log based on severity
    if level == "critical":
        logger.critical(log_msg)
    elif level == "error":
        logger.error(log_msg)
    elif level == "warning":
        logger.warning(log_msg)
    else:
        logger.info(log_msg)
        
    # Flush file handlers immediately to ensure real-time disk persistence
    for h in logger.handlers:
        try:
            h.flush()
        except Exception:
            pass

    try:
        print(formatted)
    except Exception:
        try:
            enc = getattr(sys.stdout, 'encoding', 'utf-8') or 'utf-8'
            print(formatted.encode(enc, errors='replace').decode(enc, errors='replace'))
        except Exception:
            pass
    
    # Forward to desktop GUI real-time terminal widget
    if log_cb:
        try:
            log_cb(formatted, level)
        except Exception:
            pass


# =============================================================================
# 1. CONFIGURATION MANAGEMENT
# =============================================================================

def load_config(config_path=None):
    """
    Loads JSON configuration settings from config.json (or config_path).
    If the file does not exist, populates default enterprise parameters,
    creates config.json on disk, and returns the default dictionary.
    """
    target_file = config_path or CONFIG_FILE
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
        "DELETE_LOCAL_AFTER_UPLOAD": True,
        # Section 9: Server Clean Up — Storage Monitor & Email Alerts
        "STORAGE_MONITOR_ENABLED": True,
        "STORAGE_C_DRIVE_ALERT_GB": 30,
        "STORAGE_OTHER_DRIVES_ALERT_PERCENT": 90,
        "STORAGE_INCLUDE_NETWORK_DRIVES": True,
        "STORAGE_ALERT_EMAIL_RECIPIENT": "support@spillabs.com",
        "STORAGE_ALERT_SMTP_SERVER": "smtp-mail.outlook.com",
        "STORAGE_ALERT_SMTP_PORT": 587,
        "STORAGE_ALERT_SENDER_EMAIL": "",
        "STORAGE_ALERT_SENDER_PASSWORD": "",
        "STORAGE_SHEET_TAB_NAME": "Storage Monitor",
        "STORAGE_SCAN_FREQUENCY": "Daily"
    }

    if not os.path.exists(target_file):
        emit_log(f"config.json not found at {target_file}. Creating default configuration template.", "warning")
        save_config(default_config, target_path=target_file)
        return default_config
        
    try:
        with open(target_file, 'r', encoding='utf-8-sig') as f:
            cfg = json.load(f)
            # Ensure any newly introduced settings default cleanly if missing from older configs
            for k, v in default_config.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception as e:
        emit_log(f"Corrupted config.json detected: {e}. Falling back to default settings.", "error")
        return default_config


def save_config(config_dict, target_path=None):
    """
    Serializes and writes updated configuration dictionary to config.json (or target_path).
    """
    dest = target_path or CONFIG_FILE
    try:
        with open(dest, 'w', encoding='utf-8') as f:
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
                
        # Step B: Interactive Google OAuth was REMOVED in the zero-trust build.
        # Uploads and telemetry go through the Apps Script broker (broker_client.py);
        # no client_secret.json is ever shipped, so there is nothing to authorize.
        if not creds:
            emit_log("Google OAuth is not used in this build; broker enrollment handles authentication.", "warning", log_cb)
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

def test_broker_connection(config, log_cb=None):
    """
    Validates Upload Broker availability and PC Token authentication.
    Returns a dict with 'verified' (bool), 'pc_id' (str), and 'errors' (list of str).
    """
    results = {
        "verified": False,
        "pc_id": "unknown",
        "errors": []
    }
    broker_url = (config.get("BROKER_URL") or "").rstrip("/")
    if not broker_url:
        results["errors"].append("BROKER_URL is not configured. Please enter your Apps Script endpoint in Settings.")
        emit_log("Broker connection test failed: BROKER_URL missing.", "error", log_cb)
        return results

    token_file = config.get("BROKER_TOKEN_FILE", "token.dpapi")
    token_path = None
    search_dirs = [DATA_DIR, BASE_DIR]
    search_names = [token_file, "token.dpapi", "broker_token.dat"]
    for s_dir in search_dirs:
        for s_name in search_names:
            candidate = os.path.join(s_dir, s_name)
            if os.path.exists(candidate):
                token_path = candidate
                break
        if token_path:
            break

    if not token_path:
        results["errors"].append(
            "Authentication token (token.dpapi) missing on this PC.\n"
            "Please click 'Import Token' in Settings to register your PC identity."
        )
        emit_log("Broker connection test failed: token.dpapi missing.", "error", log_cb)
        return results

    # Verify public key existence as well
    pub_file = config.get("PUBLIC_KEY_FILE", "backup_public.pem")
    pub_found = any(os.path.exists(os.path.join(d, pub_file)) for d in [DATA_DIR, BASE_DIR])
    if not pub_found:
        results["errors"].append("Encryption key (backup_public.pem) missing on this PC.")
        emit_log("Warning: backup_public.pem missing.", "warning", log_cb)

    try:
        from broker_client import load_token, verify_broker_token
        token = load_token(token_path)
        pc_id = token.split(".")[0] if "." in token else "pc-client"
        results["pc_id"] = pc_id
    except Exception as e:
        results["errors"].append(f"Failed to read local broker token: {e}")
        emit_log(f"Broker token read error: {e}", "error", log_cb)
        return results

    try:
        ok, detail = verify_broker_token(broker_url, token, timeout=10)
        if ok:
            results["verified"] = True
            results["pc_id"] = detail or pc_id
            emit_log(f"Broker connection verified. PC ID: {results['pc_id']}", "info", log_cb)
        else:
            results["errors"].append(f"Broker rejected PC Token: {detail}")
            emit_log(f"Broker rejected token: {detail}", "error", log_cb)
    except Exception as e:
        results["errors"].append(f"Network error connecting to broker ({broker_url}): {e}")
        emit_log(f"Broker unreachable: {e}", "error", log_cb)

    return results


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
    SECURE BUILD: least-privilege ACL instead of 'Everyone: Modify'.
    Access = SYSTEM (full), Administrators (full), the SQL Server service account (modify),
    and the account running this app (modify). Nobody else, including other local users.
    Folders under Program Files (SQL Server's own default backup dir) are left untouched.
    """
    try:
        norm_path = os.path.normpath(folder_path)
        if not os.path.exists(norm_path):
            os.makedirs(norm_path, exist_ok=True)
        if platform.system().lower() != "windows":
            try:
                os.chmod(norm_path, 0o700)
            except Exception:
                pass
            return True
        low = norm_path.lower()
        if "\\program files" in low:
            return True  # SQL's default backup dir already has correct ACLs
        try:
            cfg = load_config()
            sql_server = cfg.get("SQL_SERVER_INSTANCE") or cfg.get("SQL_SERVER_NAME", "")
        except Exception:
            sql_server = ""
        me = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
        grants = ["*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]
        accts = set()
        if sql_server:
            accts.add(_sql_service_account(sql_server))
        try:
            for inst in detect_sql_server_instances():
                clean_inst = inst.split("\\", 1)[1] if "\\" in inst else inst
                if clean_inst.upper() == "MSSQLSERVER":
                    accts.add("NT SERVICE\\MSSQLSERVER")
                else:
                    accts.add(f"NT SERVICE\\MSSQL${clean_inst}")
        except Exception:
            pass
        if not accts:
            accts.add("NT SERVICE\\MSSQLSERVER")
        for a in accts:
            grants.append(f"{a}:(OI)(CI)M")
        if me and "\\" in me:
            grants.append(f"{me}:(OI)(CI)M")
        # Grant FIRST, then remove inheritance, so we can never lock ourselves out.
        for g in grants:
            r = subprocess.run(["icacls", norm_path, "/grant:r", g, "/C", "/Q"],
                               shell=False, capture_output=True, text=True, timeout=15,
                               creationflags=_CREATE_NO_WINDOW)
            if r.returncode != 0:
                err = (r.stderr or r.stdout).strip()
                if "no mapping between account names and security ids" not in err.lower():
                    emit_log(f"ACL grant failed for '{g}': {err[:200]}", "warning")
        subprocess.run(["icacls", norm_path, "/inheritance:r", "/C", "/Q"],
                       shell=False, capture_output=True, text=True, timeout=15,
                       creationflags=_CREATE_NO_WINDOW)
        return True
    except Exception as e:
        emit_log(f"Could not harden folder permissions on '{folder_path}': {e}", "warning")
        return False


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


def _sql_argv(cli_type, cli_path, sql_server, sql_user, timeout, query, trust_cert, for_query):
    """Builds an argument LIST (never a shell string). Passwords go via environment, not argv."""
    argv = [cli_path, "-b", "-l", str(timeout), "-S", sql_server]
    argv += ["-U", sql_user] if sql_user else ["-E"]
    if cli_type == "sqlcmd":
        if trust_cert:
            argv.append("-C")
        if for_query:
            argv += ["-h", "-1", "-W"]
    else:  # osql.exe
        argv.append("-n")
        if for_query:
            argv += ["-h", "-1", "-w", "8000"]
    argv += ["-Q", query]
    return argv


def _sql_env(cli_type, sql_user, sql_password):
    env = os.environ.copy()
    if sql_user and sql_password:
        env["SQLCMDPASSWORD" if cli_type == "sqlcmd" else "OSQLPASSWORD"] = sql_password
    return env


def _looks_like_bad_c_flag(out, err):
    t = ((err or "") + "\n" + (out or "")).lower()
    return "-c" in t and ("unknown option" in t or "invalid option" in t or "unrecognized" in t)


def execute_sql_query_adaptive(sql_server, query, sql_user="", sql_password="", timeout=15):
    """
    Runs a read-only query with sqlcmd/osql using shell=False. Retries without -C if the
    installed client rejects that flag.  Returns (returncode, stdout, stderr).
    """
    cli_type, cli_path = find_sql_cli_executable()
    env = _sql_env(cli_type, sql_user, sql_password)

    def _run(trust):
        return subprocess.run(
            _sql_argv(cli_type, cli_path, sql_server, sql_user, timeout, query, trust, True),
            shell=False, capture_output=True, text=True, timeout=timeout + 5,
            env=env, creationflags=_CREATE_NO_WINDOW)
    try:
        res = _run(True)
        if cli_type == "sqlcmd" and _looks_like_bad_c_flag(res.stdout, res.stderr):
            res = _run(False)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)


def execute_sql_backup_command(sql_server, db_name, bak_filepath, sql_user="", sql_password="", cancel_check=None):
    """
    Executes BACKUP DATABASE using shell=False, after strict validation of the database name
    and target path, so a tampered config.json cannot inject SQL or OS commands.
    """
    if not _valid_db_name(db_name):
        return 1, "", f"Refused: invalid database name {db_name!r}"
    if "'" in bak_filepath or "\n" in bak_filepath or "\r" in bak_filepath:
        return 1, "", "Refused: invalid backup path"
    cli_type, cli_path = find_sql_cli_executable()
    backup_sql = f"BACKUP DATABASE [{db_name}] TO DISK='{bak_filepath}' WITH FORMAT"
    env = _sql_env(cli_type, sql_user, sql_password)

    def _run_cmd(trust):
        argv = _sql_argv(cli_type, cli_path, sql_server, sql_user, 15, backup_sql, trust, False)
        proc = subprocess.Popen(argv, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, creationflags=_CREATE_NO_WINDOW)
        backup_controller.set_active_process(proc)
        try:
            stdout, stderr = proc.communicate()
            return proc.returncode, stdout, stderr
        finally:
            backup_controller.clear_active_process()

    code, out, err = _run_cmd(True)
    if cli_type == "sqlcmd" and _looks_like_bad_c_flag(out, err):
        code, out, err = _run_cmd(False)
    return code, out, err


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
        
    ok, why = broker_ready(config)
    if not ok:
        emit_log(f"Secure upload is not configured: {why}. Aborting backup cycle.", "critical", log_cb)
        if status_cb:
            status_cb("Secure upload not configured")
        return False, f"Secure upload not configured: {why}"

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

            # Encrypt with the PUBLIC key(s) (private keys stay offline), then upload via the broker.
            enc_path = os.path.splitext(backup_zip)[0] + ".dbk2"
            pub_key = os.path.join(BASE_DIR, config.get("PUBLIC_KEY_FILE", "backup_public.pem"))
            escrow_key = os.path.join(BASE_DIR, config.get("ESCROW_KEY_FILE", "escrow_public.pem"))
            _log = lambda m, l="info": emit_log(m, l, log_cb)
            link = None
            try:
                if status_cb:
                    status_cb(f"Encrypting {file_name} (DBK2)...")
                allow_no_escrow = config.get("ALLOW_NO_ESCROW", False)
                if not os.path.exists(escrow_key) and not allow_no_escrow:
                    raise ValueError(
                        f"Escrow key '{os.path.basename(escrow_key)}' missing! DBK2 encryption requires an escrow key "
                        "by default. Either place escrow_public.pem in the application directory or set ALLOW_NO_ESCROW: true in config.json."
                    )
                escrow_to_pass = escrow_key if os.path.exists(escrow_key) else None

                encrypt_file(
                    backup_zip, enc_path, pub_key,
                    cancel_check=cancel_check,
                    escrow_key_path=escrow_to_pass,
                    allow_no_escrow=allow_no_escrow,
                    db_name=db_name
                )
                link = secure_upload(
                    enc_path, db_name, config, BASE_DIR,
                    log_cb=_log, progress_cb=_upload_progress_bridge,
                    telemetry_cb=telemetry_cb, cancel_check=cancel_check, status_cb=status_cb)
            except InterruptedError:
                emit_log(f"Encryption of {file_name} cancelled.", "warning", log_cb)
            except Exception as up_err:
                emit_log(f"Encrypt/upload error for {db_name}: {up_err}", "error", log_cb)
            finally:
                try:
                    if os.path.exists(enc_path):
                        os.remove(enc_path)
                except Exception:
                    pass

            if (cancel_check and cancel_check()) or backup_controller.is_cancelled():
                emit_log(f"EMERGENCY STOP: Upload stopped for {db_name}.", "warning", log_cb)
                if status_cb:
                    status_cb("Backup Cancelled by User")
                return False, "Backup operation was cancelled by user."
            
            # Step 3: Log telemetry to Google Sheets
            if link:
                if status_cb:
                    status_cb(f"Logging {file_name} to Google Sheet...")
                emit_log(f"AUDIT: uploaded and verified {link} ({file_size_str})", "info", log_cb)
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
        res = subprocess.run(["schtasks", "/query", "/tn", SYSTEM_SERVICE_TASK_NAME, "/fo", "CSV", "/nh"], capture_output=True, text=True, timeout=10)
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
        res = subprocess.run(["schtasks", "/query", "/tn", TASK_SCHEDULER_NAME, "/fo", "CSV", "/nh"], capture_output=True, text=True, timeout=10)
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
        res = subprocess.run(["schtasks", "/query", "/tn", DAEMON_SERVICE_TASK_NAME, "/fo", "CSV", "/nh"], capture_output=True, text=True, timeout=10)
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

    # Windows Task Scheduler Implementation (macOS / Linux are unsupported and untested)
    if platform.system().lower() != "windows":
        emit_log("Non-Windows platforms (macOS/Linux) are unsupported and untested.")
        return False, "Operating System unsupported. Database Cloud Backup requires Windows."

    # Windows Task Scheduler Implementation
    if executable_path.startswith("python "):
        cmd_run_subp = f'{executable_path} --auto'
        cmd_run_elev = f'{executable_path} --auto'
    else:
        cmd_run_subp = f'"{executable_path}" --auto'
        cmd_run_elev = f'\\"{executable_path}\\" --auto'

    if is_daily:
        schedule_args = f'/sc daily /st {time_str}'
    else:
        days_csv = ",".join(ordered_days)
        schedule_args = f'/sc weekly /d {days_csv} /st {time_str}'

    if as_system_service:
        # First remove any user-level task to avoid conflicting double-executions
        subprocess.run(["schtasks", "/delete", "/tn", TASK_SCHEDULER_NAME, "/f"], capture_output=True)
        
        target_task = SYSTEM_SERVICE_TASK_NAME
        cmd_args = ["schtasks", "/create", "/tn", target_task, "/tr", cmd_run_subp, "/ru", "NT AUTHORITY\\SYSTEM", "/rl", "HIGHEST", "/f"]
        if days == "EVERYDAY":
            cmd_args.extend(["/sc", "daily", "/st", time_str])
        else:
            cmd_args.extend(["/sc", "weekly", "/d", ",".join(ordered_days), "/st", time_str])
        
        if not is_admin():
            cmd_str = f'schtasks /create /tn "{target_task}" /tr "{cmd_run_elev}" {schedule_args} /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
            ok = run_command_elevated(cmd_str)
            if ok:
                emit_log(f"Unattended System Service '{target_task}' configured via elevated prompt.")
                if on_boot:
                    boot_cmd = f'schtasks /create /tn "{DAEMON_SERVICE_TASK_NAME}" /tr "{cmd_run_elev}" /sc ONSTART /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
                    run_command_elevated(boot_cmd)
                return True, f"Windows System Service Active: {friendly_schedule} (Unattended Session 0)."
            else:
                return False, "Administrator elevation was cancelled or denied."
        else:
            res = subprocess.run(cmd_args, capture_output=True, text=True)
            if res.returncode == 0:
                emit_log(f"Unattended System Service '{target_task}' created successfully.")
                if on_boot:
                    boot_args = ["schtasks", "/create", "/tn", DAEMON_SERVICE_TASK_NAME, "/tr", cmd_run_subp, "/sc", "ONSTART", "/ru", "NT AUTHORITY\\SYSTEM", "/rl", "HIGHEST", "/f"]
                    subprocess.run(boot_args, capture_output=True)
                return True, f"Windows System Service Active: {friendly_schedule} (Unattended Session 0)."
            else:
                err = res.stderr or res.stdout
                return False, f"Scheduler error: {err}"
    else:
        # First remove any system-level task to avoid double-runs
        subprocess.run(["schtasks", "/delete", "/tn", SYSTEM_SERVICE_TASK_NAME, "/f"], capture_output=True)
        subprocess.run(["schtasks", "/delete", "/tn", DAEMON_SERVICE_TASK_NAME, "/f"], capture_output=True)
        
        target_task = TASK_SCHEDULER_NAME
        user_cmd_args = ["schtasks", "/create", "/tn", target_task, "/tr", cmd_run_subp, "/f"]
        if days == "EVERYDAY":
            user_cmd_args.extend(["/sc", "daily", "/st", time_str])
        else:
            user_cmd_args.extend(["/sc", "weekly", "/d", ",".join(ordered_days), "/st", time_str])
            
        res = subprocess.run(user_cmd_args, capture_output=True, text=True)
        if res.returncode == 0:
            emit_log(f"Standard user task '{target_task}' created successfully ({friendly_schedule}).")
            return True, f"Scheduled successfully: {friendly_schedule}."
        else:
            err = res.stderr or res.stdout
            if not is_admin() and ("access is denied" in (err or "").lower() or "denied" in (err or "").lower()):
                emit_log(f"User task creation denied. Requesting elevated administrator registration...")
                elev_sched = " ".join(user_cmd_args[6:])
                cmd_str = f'schtasks /create /tn "{target_task}" /tr "{cmd_run_elev}" {elev_sched} /f'
                if run_command_elevated(cmd_str):
                    emit_log(f"Task '{target_task}' registered via elevated UAC prompt ({friendly_schedule}).")
                    return True, f"Scheduled successfully (Elevated): {friendly_schedule}."
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
        cmd_args = ["schtasks", "/delete", "/tn", tn, "/f"]
        res = subprocess.run(cmd_args, capture_output=True, text=True)
        if res.returncode == 0:
            removed_any = True
        elif not is_admin():
            cmd_str = f'schtasks /delete /tn "{tn}" /f'
            if run_command_elevated(cmd_str):
                removed_any = True
                
    emit_log("Windows automation schedules removed.")
    return True, "Automated schedules removed."


# =============================================================================
# 7B. PERFORMANCE MAINTENANCE TASK SCHEDULER
# =============================================================================

PERF_TASK_NAME = "Database Cloud Backup - Performance Maintenance"
PERF_BOOT_TASK_NAME = "Database Cloud Backup - Performance Boot Recovery"


def get_performance_scheduler_status():
    """
    Queries Windows Task Scheduler for the performance maintenance task status.
    Returns (active: bool, status_desc: str, next_run: str).
    """
    if platform.system().lower() != "windows":
        return False, "Not Scheduled", ""
    try:
        res = subprocess.run(
            ["schtasks", "/query", "/tn", PERF_TASK_NAME, "/fo", "LIST", "/v"],
            capture_output=True, text=True, timeout=8
        )
        if res.returncode == 0:
            status = "Ready"
            next_run = ""
            for line in res.stdout.splitlines():
                if line.strip().startswith("Status:"):
                    status = line.split(":", 1)[1].strip()
                elif line.strip().startswith("Next Run Time:"):
                    next_run = line.split(":", 1)[1].strip()
            return True, f"Active ({status})", next_run
    except Exception:
        pass
    return False, "Not Scheduled", ""


def enable_performance_scheduler(executable_path=None, freq="Weekly", day="SUN", time_str="03:00", day_of_month=1, on_boot=False):
    """
    Registers the Performance Query & Re-Indexing Maintenance automated task in Windows Task Scheduler.
    Runs 'DatabaseBackupApp.exe --performance' (or 'python auto_backup.py --performance').
    Supports:
      - Daily:   /sc daily /st HH:mm
      - Weekly:  /sc weekly /d {day} /st HH:mm (e.g. SUN, MON)
      - Monthly: /sc monthly /d {day_of_month} /st HH:mm (e.g. 1 - 31)
    """
    if platform.system().lower() != "windows":
        return False, "Windows required for Task Scheduler."

    if not executable_path:
        if getattr(sys, 'frozen', False):
            executable_path = sys.executable
        else:
            executable_path = f'python "{os.path.join(BASE_DIR, "auto_backup.py")}"'

    if executable_path.startswith("python "):
        cmd_run_subp = f'{executable_path} --performance'
        cmd_run_elev = f'{executable_path} --performance'
    else:
        cmd_run_subp = f'"{executable_path}" --performance'
        cmd_run_elev = f'\\"{executable_path}\\" --performance'

    freq_norm = str(freq).strip().capitalize()
    time_val = str(time_str).strip()
    if not re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$", time_val):
        time_val = "03:00"

    day_map = {
        "MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday",
        "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"
    }

    if freq_norm == "Daily":
        schedule_args = ["/sc", "daily", "/st", time_val]
        friendly_plan = f"Every Day at {time_val}"
    elif freq_norm == "Monthly":
        try:
            dom = max(1, min(int(day_of_month), 31))
        except Exception:
            dom = 1
        schedule_args = ["/sc", "monthly", "/d", str(dom), "/st", time_val]
        friendly_plan = f"Day {dom} of every month at {time_val}"
    else:  # Weekly
        day_code = str(day).strip().upper()[:3]
        if day_code not in day_map:
            day_code = "SUN"
        schedule_args = ["/sc", "weekly", "/d", day_code, "/st", time_val]
        friendly_plan = f"Every {day_map.get(day_code, day_code)} at {time_val}"

    # Remove existing tasks to ensure clean replacement
    subprocess.run(["schtasks", "/delete", "/tn", PERF_TASK_NAME, "/f"], capture_output=True)
    subprocess.run(["schtasks", "/delete", "/tn", PERF_BOOT_TASK_NAME, "/f"], capture_output=True)

    if is_admin():
        cmd_args = ["schtasks", "/create", "/tn", PERF_TASK_NAME, "/tr", cmd_run_subp, "/ru", "NT AUTHORITY\\SYSTEM", "/rl", "HIGHEST", "/f"] + schedule_args
        res = subprocess.run(cmd_args, capture_output=True, text=True)
        if res.returncode == 0:
            emit_log(f"Performance maintenance task '{PERF_TASK_NAME}' registered (SYSTEM): {friendly_plan}")
            if on_boot:
                boot_args = ["schtasks", "/create", "/tn", PERF_BOOT_TASK_NAME, "/tr", cmd_run_subp, "/sc", "ONSTART", "/ru", "NT AUTHORITY\\SYSTEM", "/rl", "HIGHEST", "/f"]
                subprocess.run(boot_args, capture_output=True)
            return True, f"Automation Active: {friendly_plan} (System Service)"
        else:
            err = res.stderr or res.stdout
            return False, f"Scheduler error: {err}"
    else:
        # Try elevated creation
        elev_str = f'schtasks /create /tn "{PERF_TASK_NAME}" /tr "{cmd_run_elev}" {" ".join(schedule_args)} /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
        ok = run_command_elevated(elev_str)
        if ok:
            emit_log(f"Performance maintenance task '{PERF_TASK_NAME}' registered via elevated UAC: {friendly_plan}")
            if on_boot:
                elev_boot = f'schtasks /create /tn "{PERF_BOOT_TASK_NAME}" /tr "{cmd_run_elev}" /sc ONSTART /ru "NT AUTHORITY\\SYSTEM" /rl HIGHEST /f'
                run_command_elevated(elev_boot)
            return True, f"Automation Active: {friendly_plan} (System Service)"
        else:
            # Fallback to current user task
            user_args = ["schtasks", "/create", "/tn", PERF_TASK_NAME, "/tr", cmd_run_subp, "/f"] + schedule_args
            res = subprocess.run(user_args, capture_output=True, text=True)
            if res.returncode == 0:
                emit_log(f"Performance maintenance task '{PERF_TASK_NAME}' registered (User account): {friendly_plan}")
                if on_boot:
                    user_boot = ["schtasks", "/create", "/tn", PERF_BOOT_TASK_NAME, "/tr", cmd_run_subp, "/sc", "ONLOGON", "/f"]
                    subprocess.run(user_boot, capture_output=True)
                return True, f"Automation Active: {friendly_plan} (User Task)"
            err = res.stderr or res.stdout
            return False, f"Scheduler error: {err}"


def disable_performance_scheduler():
    """
    Unregisters the performance maintenance scheduled task and boot recovery task.
    """
    if platform.system().lower() != "windows":
        return True, "Disabled"
    res1 = subprocess.run(["schtasks", "/delete", "/tn", PERF_TASK_NAME, "/f"], capture_output=True, text=True)
    subprocess.run(["schtasks", "/delete", "/tn", PERF_BOOT_TASK_NAME, "/f"], capture_output=True)
    if res1.returncode == 0:
        emit_log(f"Performance maintenance task '{PERF_TASK_NAME}' removed.")
        return True, "Maintenance automation disabled."
    else:
        if "cannot find" in (res1.stderr or "").lower() or "not found" in (res1.stderr or "").lower():
            return True, "Maintenance automation is not active."
        elif not is_admin():
            cmd_str = f'schtasks /delete /tn "{PERF_TASK_NAME}" /f'
            if run_command_elevated(cmd_str):
                run_command_elevated(f'schtasks /delete /tn "{PERF_BOOT_TASK_NAME}" /f')
                emit_log(f"Performance maintenance task '{PERF_TASK_NAME}' removed via elevation.")
                return True, "Maintenance automation disabled."
        return False, f"Could not disable task: {res1.stderr or res1.stdout}"


# =============================================================================
# 8. WINDOWS SQL SERVER DISCOVERY
# =============================================================================

def detect_sql_server_instances():
    """
    Auto-discovers locally installed Microsoft SQL Server instances.
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
            res = subprocess.run(["sc", "query", "state=", "all"], capture_output=True, text=True)
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


# =============================================================================
# 9. SERVER CLEAN UP — STORAGE MONITORING, SHEET LOGGING & EMAIL ALERTS
# =============================================================================
# Scans all storage drives (local fixed, removable, and mapped network/shared),
# logs the current available capacity to a dedicated "Storage Monitor" worksheet
# tab in the linked Google Spreadsheet (horizontal layout: drives as columns,
# daily scans as rows), and sends a High Importance Outlook email alert to
# support@spillabs.com when any drive breaches its configured threshold.
#
# Dual-Threshold Alert Logic:
#   C: Drive (System): Alert when FREE space falls BELOW a GB limit (default 30 GB)
#   All Other Drives:  Alert when USAGE exceeds a percentage limit (default 90%)
# =============================================================================

import smtplib
import ctypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# Windows drive type constants from kernel32.GetDriveTypeW
_DRIVE_TYPE_NAMES = {
    0: "Unknown",
    1: "No Root",
    2: "Removable",
    3: "Fixed",
    4: "Network",
    5: "CD-ROM",
    6: "RAM Disk"
}


def scan_storage_drives(include_network=True, log_cb=None):
    """
    Scans all mounted storage drives on the server (local fixed, removable,
    and optionally mapped network/shared drives).

    Uses built-in Python APIs (shutil.disk_usage + ctypes kernel32) with zero
    external dependencies.

    Returns a list of drive info dictionaries sorted by drive letter:
    [
        {
            "drive_letter": "C:",
            "label": "Windows",
            "total_gb": 237.86,
            "used_gb": 180.21,
            "free_gb": 57.65,
            "usage_percent": 75.8,
            "drive_type": "Fixed",
            "drive_type_id": 3
        },
        ...
    ]
    """
    drives = []
    emit_log("Scanning storage drives...", "info", log_cb)

    try:
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    except Exception:
        get_drive_type = None

    for letter_code in range(65, 91):  # A-Z
        drive_letter = chr(letter_code) + ":"
        drive_root = drive_letter + "\\"

        if not os.path.exists(drive_root):
            continue

        # Determine drive type via Windows API
        drive_type_id = 0
        if get_drive_type:
            try:
                drive_type_id = get_drive_type(drive_root)
            except Exception:
                pass

        drive_type_name = _DRIVE_TYPE_NAMES.get(drive_type_id, "Unknown")

        # Skip CD-ROM, RAM Disk, and unknown/no-root drives
        if drive_type_id in (0, 1, 5, 6):
            continue

        # Skip network drives if not requested
        if drive_type_id == 4 and not include_network:
            continue

        # Get disk usage via shutil (built-in, no dependency)
        try:
            usage = shutil.disk_usage(drive_root)
            total_gb = round(usage.total / (1024 ** 3), 2)
            used_gb = round(usage.used / (1024 ** 3), 2)
            free_gb = round(usage.free / (1024 ** 3), 2)
            usage_pct = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
        except (PermissionError, OSError) as e:
            emit_log(f"  Skipping {drive_letter} (access denied or unavailable): {e}", "warning", log_cb)
            continue

        # Get volume label via Windows API
        label = ""
        try:
            vol_name_buf = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(
                drive_root, vol_name_buf, 261, None, None, None, None, 0
            )
            label = vol_name_buf.value or ""
        except Exception:
            pass

        drive_info = {
            "drive_letter": drive_letter,
            "label": label,
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "usage_percent": usage_pct,
            "drive_type": drive_type_name,
            "drive_type_id": drive_type_id
        }
        drives.append(drive_info)
        emit_log(f"  {drive_letter} [{label or drive_type_name}] — Total: {total_gb:.2f} GB, Free: {free_gb:.2f} GB ({usage_pct}% used)", "info", log_cb)

    # Also detect UNC-mapped network shares from 'net use'
    if include_network:
        try:
            res = subprocess.run(["net", "use"], capture_output=True, text=True, timeout=10)
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and ":" in parts[1] and "\\\\" in line:
                    mapped_letter = parts[1].strip()
                    mapped_root = mapped_letter + "\\"
                    # Skip if already scanned
                    if any(d["drive_letter"] == mapped_letter for d in drives):
                        continue
                    if os.path.exists(mapped_root):
                        try:
                            usage = shutil.disk_usage(mapped_root)
                            total_gb = round(usage.total / (1024 ** 3), 2)
                            free_gb = round(usage.free / (1024 ** 3), 2)
                            used_gb = round(usage.used / (1024 ** 3), 2)
                            usage_pct = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0.0
                            unc_path = ""
                            for p in parts[2:]:
                                if "\\\\" in p:
                                    unc_path = p
                                    break
                            drives.append({
                                "drive_letter": mapped_letter,
                                "label": unc_path or "Network Share",
                                "total_gb": total_gb,
                                "used_gb": used_gb,
                                "free_gb": free_gb,
                                "usage_percent": usage_pct,
                                "drive_type": "Network",
                                "drive_type_id": 4
                            })
                            emit_log(f"  {mapped_letter} [Network: {unc_path}] — Total: {total_gb:.2f} GB, Free: {free_gb:.2f} GB ({usage_pct}% used)", "info", log_cb)
                        except Exception:
                            pass
        except Exception:
            pass

    emit_log(f"Storage scan complete: {len(drives)} drive(s) detected.", "info", log_cb)
    return drives


def evaluate_drive_alerts(drives, c_drive_alert_gb=30, other_drives_alert_pct=90):
    """
    Evaluates which drives have breached their alert thresholds.

    Dual-threshold logic:
    - C: Drive: Alert if free_gb <= c_drive_alert_gb
    - All other drives: Alert if usage_percent >= other_drives_alert_pct

    Returns a list of critical drive dicts with an added 'alert_reason' field.
    """
    critical = []
    for d in drives:
        letter = d["drive_letter"].upper()
        if letter == "C:":
            if d["free_gb"] <= c_drive_alert_gb:
                d_copy = dict(d)
                d_copy["alert_reason"] = f"Below {c_drive_alert_gb} GB free limit ({d['free_gb']:.2f} GB remaining)"
                critical.append(d_copy)
        else:
            if d["usage_percent"] >= other_drives_alert_pct:
                d_copy = dict(d)
                d_copy["alert_reason"] = f"{d['usage_percent']}% full (threshold: {other_drives_alert_pct}%)"
                critical.append(d_copy)
    return critical


def update_storage_sheet(creds, sheet_id, drives, tab_name="Storage Monitor", log_cb=None):
    """
    Logs the drive scan results to a dedicated worksheet tab in the linked
    Google Spreadsheet using a HORIZONTAL layout:

    Row 1 (Header):     Date & Time | Drive C (237.86 GB) | Drive D (500 GB) | ...
    Row 2 (Sub-header): <empty>     | currently available storage capacity | ...
    Row 3+ (Data):      2026-09-29  | 57.65 GB            | 120.00 GB        | ...

    Drives are columns, daily scans are rows. The header includes total capacity.
    Each data cell contains the currently available (free) storage at scan time.

    Dynamically adds new columns if a new drive appears on subsequent scans.
    """
    if not drives:
        emit_log("No drives to log to Google Sheet.", "warning", log_cb)
        return False

    emit_log(f"Logging storage scan to Google Sheet (tab: '{tab_name}')...", "info", log_cb)

    try:
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(sheet_id)

        # Get or create the Storage Monitor worksheet tab
        worksheet = None
        for ws in spreadsheet.worksheets():
            if ws.title.lower() == tab_name.lower():
                worksheet = ws
                break

        server_name = socket.gethostname()

        if worksheet is None:
            # First-time setup: create the tab with header and sub-header
            worksheet = spreadsheet.add_worksheet(title=tab_name, rows=100, cols=len(drives) + 2)
            emit_log(f"Created new worksheet tab: '{tab_name}'", "info", log_cb)

            # Build header row: Date & Time | Server | Drive C (237.86 GB) | Drive D (500 GB) | ...
            header_row = ["Date & Time", "Server"]
            for d in drives:
                label_part = f" - {d['label']}" if d['label'] else ""
                if d["drive_type_id"] == 4:
                    col_name = f"shared/mapped {d['drive_letter']}{label_part} ({d['total_gb']:.2f} GB)"
                else:
                    col_name = f"Drive {d['drive_letter'][0]}{label_part} ({d['total_gb']:.2f} GB)"
                header_row.append(col_name)

            # Build sub-header row
            sub_header_row = ["", ""]
            for _ in drives:
                sub_header_row.append("currently available storage capacity")

            worksheet.insert_row(header_row, index=1)
            worksheet.insert_row(sub_header_row, index=2)

            # Append the first data row
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_row = [timestamp, server_name]
            for d in drives:
                data_row.append(f"{d['free_gb']:.2f} GB")
            worksheet.append_row(data_row)

        else:
            # Tab already exists: read existing headers to map columns correctly
            existing_headers = worksheet.row_values(1)

            # Build a mapping from drive letter to column index
            drive_col_map = {}  # drive_letter -> column index (0-based)
            for col_idx, header in enumerate(existing_headers):
                if col_idx < 2:
                    continue  # Skip "Date & Time" and "Server"
                # Extract drive letter from header like "Drive C - Windows (237.86 GB)"
                header_upper = header.upper()
                for d in drives:
                    letter_char = d["drive_letter"][0].upper()
                    if f"DRIVE {letter_char}" in header_upper or f"SHARED/MAPPED {d['drive_letter'].upper()}" in header_upper:
                        drive_col_map[d["drive_letter"]] = col_idx
                        break

            # Check for new drives that need new columns
            new_drives = [d for d in drives if d["drive_letter"] not in drive_col_map]
            if new_drives:
                sub_header_row = worksheet.row_values(2) if len(worksheet.get_all_values()) >= 2 else []
                for new_d in new_drives:
                    label_part = f" - {new_d['label']}" if new_d['label'] else ""
                    if new_d["drive_type_id"] == 4:
                        col_name = f"shared/mapped {new_d['drive_letter']}{label_part} ({new_d['total_gb']:.2f} GB)"
                    else:
                        col_name = f"Drive {new_d['drive_letter'][0]}{label_part} ({new_d['total_gb']:.2f} GB)"
                    existing_headers.append(col_name)
                    col_idx = len(existing_headers) - 1
                    drive_col_map[new_d["drive_letter"]] = col_idx

                # Update header and sub-header rows with new columns
                worksheet.update(range_name='1:1', values=[existing_headers])
                full_sub = ["", ""] + ["currently available storage capacity"] * (len(existing_headers) - 2)
                worksheet.update(range_name='2:2', values=[full_sub])
                emit_log(f"Added {len(new_drives)} new drive column(s) to storage sheet.", "info", log_cb)

            # Append the data row with values in correct column positions
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data_row = [""] * len(existing_headers)
            data_row[0] = timestamp
            data_row[1] = server_name
            for d in drives:
                if d["drive_letter"] in drive_col_map:
                    data_row[drive_col_map[d["drive_letter"]]] = f"{d['free_gb']:.2f} GB"
            worksheet.append_row(data_row)

        emit_log(f"Storage scan logged to Google Sheet successfully.", "info", log_cb)
        return True

    except Exception as e:
        emit_log(f"Google Sheets storage logging error: {e}", "error", log_cb)
        return False


def save_smtp_password(password):
    """Encrypts SMTP password via Windows DPAPI (machine scope) and saves to storage_smtp_pass.dat."""
    path = os.path.join(BASE_DIR, "storage_smtp_pass.dat")
    data = password.encode('utf-8')
    try:
        import win32crypt
        data = win32crypt.CryptProtectData(data, "BackupSMTPPassword", None, None, None, 0x4)
    except Exception:
        pass
    with open(path, "wb") as f:
        f.write(data)


def load_smtp_password():
    """Decrypts SMTP password from storage_smtp_pass.dat using Windows DPAPI."""
    path = os.path.join(BASE_DIR, "storage_smtp_pass.dat")
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        data = f.read()
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1].decode('utf-8').strip()
    except Exception:
        pass
    return data.decode('utf-8').strip()


def send_storage_alert_email(critical_drives, config, log_cb=None):
    """
    Sends a HIGH IMPORTANCE HTML email via Outlook SMTP when one or more
    drives breach their storage alert thresholds.
    SMTP password is read from DPAPI-protected storage_smtp_pass.dat if not in config.json.
    """
    if not critical_drives:
        return False

    smtp_server = config.get("STORAGE_ALERT_SMTP_SERVER", "smtp-mail.outlook.com")
    smtp_port = config.get("STORAGE_ALERT_SMTP_PORT", 587)
    sender_email = config.get("STORAGE_ALERT_SENDER_EMAIL", "")
    sender_password = config.get("STORAGE_ALERT_SENDER_PASSWORD", "") or load_smtp_password()
    recipient = config.get("STORAGE_ALERT_EMAIL_RECIPIENT", "support@spillabs.com")

    if not sender_email or not sender_password:
        emit_log("Storage alert email skipped: Sender email or password not configured.", "warning", log_cb)
        return False

    server_name = socket.gethostname()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    drive_count = len(critical_drives)

    subject = f"⚠️ CRITICAL: Storage Alert — {server_name} — {drive_count} Drive{'s' if drive_count > 1 else ''} Almost Full"

    # Build HTML email body with professional table
    drive_rows_html = ""
    for d in critical_drives:
        label_str = f" ({d['label']})" if d.get('label') else ""
        drive_rows_html += f"""
        <tr>
            <td style="padding: 10px 15px; border: 1px solid #374151; font-weight: bold; color: #f87171;">
                {d['drive_letter']}{label_str}
            </td>
            <td style="padding: 10px 15px; border: 1px solid #374151; text-align: center;">
                {d['total_gb']:.2f} GB
            </td>
            <td style="padding: 10px 15px; border: 1px solid #374151; text-align: center; color: #f87171; font-weight: bold;">
                {d['free_gb']:.2f} GB
            </td>
            <td style="padding: 10px 15px; border: 1px solid #374151; text-align: center;">
                {d['usage_percent']}%
            </td>
            <td style="padding: 10px 15px; border: 1px solid #374151; color: #fbbf24;">
                {d.get('alert_reason', 'Threshold breached')}
            </td>
        </tr>"""

    html_body = f"""
    <html>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #111827; color: #e5e7eb; margin: 0; padding: 20px;">
        <div style="max-width: 750px; margin: 0 auto; background-color: #1f2937; border-radius: 12px; padding: 30px; border: 1px solid #374151;">

            <div style="text-align: center; margin-bottom: 25px;">
                <h1 style="color: #f87171; margin: 0; font-size: 24px;">⚠️ Server Storage Alert</h1>
                <p style="color: #9ca3af; margin-top: 8px; font-size: 14px;">Automated Storage Monitoring System</p>
            </div>

            <table style="width: 100%; margin-bottom: 20px; font-size: 14px;">
                <tr>
                    <td style="padding: 5px 0; color: #9ca3af;">Server Name:</td>
                    <td style="padding: 5px 0; color: #ffffff; font-weight: bold;">{server_name}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; color: #9ca3af;">Scan Time:</td>
                    <td style="padding: 5px 0; color: #ffffff;">{timestamp}</td>
                </tr>
                <tr>
                    <td style="padding: 5px 0; color: #9ca3af;">Critical Drives:</td>
                    <td style="padding: 5px 0; color: #f87171; font-weight: bold;">{drive_count}</td>
                </tr>
            </table>

            <p style="color: #fbbf24; font-size: 14px; margin-bottom: 15px;">
                The following drive(s) have critically low available storage:
            </p>

            <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 25px;">
                <thead>
                    <tr style="background-color: #374151;">
                        <th style="padding: 10px 15px; border: 1px solid #4b5563; text-align: left; color: #d1d5db;">Drive</th>
                        <th style="padding: 10px 15px; border: 1px solid #4b5563; text-align: center; color: #d1d5db;">Total Capacity</th>
                        <th style="padding: 10px 15px; border: 1px solid #4b5563; text-align: center; color: #d1d5db;">Free Space</th>
                        <th style="padding: 10px 15px; border: 1px solid #4b5563; text-align: center; color: #d1d5db;">Used %</th>
                        <th style="padding: 10px 15px; border: 1px solid #4b5563; text-align: left; color: #d1d5db;">Alert Reason</th>
                    </tr>
                </thead>
                <tbody>
                    {drive_rows_html}
                </tbody>
            </table>

            <div style="background-color: #7f1d1d; border-radius: 8px; padding: 15px; margin-bottom: 20px;">
                <p style="margin: 0; color: #fca5a5; font-size: 14px;">
                    ⚡ <strong>Action Required:</strong> Please take immediate action to free disk space
                    or expand storage on this server to prevent service disruption.
                </p>
            </div>

            <hr style="border: 0; border-top: 1px solid #374151; margin: 20px 0;">
            <p style="color: #6b7280; font-size: 11px; text-align: center;">
                This is an automated alert from the Enterprise Database Cloud Backup Automation System.<br>
                Server: {server_name} | Generated: {timestamp}
            </p>
        </div>
    </body>
    </html>"""

    # Plain text fallback for non-HTML email clients
    plain_lines = [
        f"⚠️ SERVER STORAGE ALERT",
        f"Server: {server_name}",
        f"Scan Time: {timestamp}",
        "",
        "The following drives have critically low storage:",
        ""
    ]
    for d in critical_drives:
        plain_lines.append(f"  {d['drive_letter']} — Total: {d['total_gb']:.2f} GB, Free: {d['free_gb']:.2f} GB, Used: {d['usage_percent']}%")
        plain_lines.append(f"    Reason: {d.get('alert_reason', 'Threshold breached')}")
        plain_lines.append("")
    plain_lines.append("Please take immediate action to free disk space or expand storage.")
    plain_text = "\n".join(plain_lines)

    # Compose MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = recipient
    # HIGH IMPORTANCE headers — ensures top placement in Outlook sorted by Importance
    msg["X-Priority"] = "1"
    msg["X-MSMail-Priority"] = "High"
    msg["Importance"] = "High"

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    emit_log(f"Sending storage alert email to {recipient} ({drive_count} critical drive(s))...", "info", log_cb)

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        emit_log(f"Storage alert email sent successfully to {recipient}.", "info", log_cb)
        return True
    except smtplib.SMTPAuthenticationError as e:
        emit_log(f"SMTP authentication failed: {e}. Check sender email/password or enable App Password.", "error", log_cb)
        return False
    except Exception as e:
        emit_log(f"Failed to send storage alert email: {e}", "error", log_cb)
        return False


def send_test_storage_email(config, log_cb=None):
    """
    Sends a test email to verify SMTP connectivity and credentials.
    Uses the same High Importance headers as real alerts.
    """
    smtp_server = config.get("STORAGE_ALERT_SMTP_SERVER", "smtp-mail.outlook.com")
    smtp_port = config.get("STORAGE_ALERT_SMTP_PORT", 587)
    sender_email = config.get("STORAGE_ALERT_SENDER_EMAIL", "")
    sender_password = config.get("STORAGE_ALERT_SENDER_PASSWORD", "")
    recipient = config.get("STORAGE_ALERT_EMAIL_RECIPIENT", "support@spillabs.com")

    if not sender_email or not sender_password:
        emit_log("Test email failed: Sender email or password not configured.", "error", log_cb)
        return False, "Sender email or password not configured."

    server_name = socket.gethostname()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    msg = MIMEMultipart()
    msg["Subject"] = f"✅ Storage Monitor Test — {server_name} — Email Configuration Verified"
    msg["From"] = sender_email
    msg["To"] = recipient
    msg["X-Priority"] = "1"
    msg["X-MSMail-Priority"] = "High"
    msg["Importance"] = "High"

    body = (
        f"This is a test email from the Enterprise Database Cloud Backup Automation System.\n\n"
        f"Server: {server_name}\n"
        f"Time: {timestamp}\n\n"
        f"Storage alert emails are now correctly configured.\n"
        f"Alerts will be sent to: {recipient}\n"
    )
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        emit_log(f"Test email sent successfully to {recipient}.", "info", log_cb)
        return True, f"Test email sent to {recipient}."
    except smtplib.SMTPAuthenticationError as e:
        err = f"SMTP authentication failed: {e}"
        emit_log(err, "error", log_cb)
        return False, err
    except Exception as e:
        err = f"Failed to send test email: {e}"
        emit_log(err, "error", log_cb)
        return False, err


def run_storage_monitor(config=None, log_cb=None, status_cb=None):
    """
    Master orchestrator for the Server Clean Up storage monitoring workflow.

    Workflow:
    1. Scan all storage drives (local + network/shared).
    2. Log results to the 'Storage Monitor' tab in the linked Google Sheet.
    3. Evaluate drives against dual-threshold alert rules.
    4. If any drive is critical → send High Importance email alert.

    Returns: (success, summary_message, drives_list, critical_list)
    """
    if not config:
        config = load_config()

    if not config.get("STORAGE_MONITOR_ENABLED", True):
        msg = "Storage monitoring is disabled in configuration."
        emit_log(msg, "info", log_cb)
        return True, msg, [], []

    emit_log("=" * 60, "info", log_cb)
    emit_log("STARTING SERVER STORAGE MONITORING SCAN", "info", log_cb)
    emit_log("=" * 60, "info", log_cb)

    if status_cb:
        status_cb("Scanning storage drives...")

    # Step 1: Scan all drives
    include_network = config.get("STORAGE_INCLUDE_NETWORK_DRIVES", True)
    drives = scan_storage_drives(include_network=include_network, log_cb=log_cb)

    if not drives:
        msg = "No accessible storage drives found."
        emit_log(msg, "warning", log_cb)
        if status_cb:
            status_cb("No drives detected")
        return True, msg, [], []

    # Step 2: Log to Google Sheet via Telemetry Broker (No client-side Google OAuth)
    if status_cb:
        status_cb("Logging storage data to Google Sheet via Telemetry Broker...")

    telemetry_broker_url = config.get("TELEMETRY_BROKER_URL", config.get("BROKER_URL", ""))
    token_filename = config.get("BROKER_TOKEN_FILE", "token.dpapi")
    prog_data = os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData")
    search_dirs = [DATA_DIR, os.path.join(prog_data, "DatabaseBackupApp"), BASE_DIR]
    for s_dir in search_dirs:
        for s_name in [token_filename, "token.dpapi", "broker_token.dat"]:
            candidate = os.path.join(s_dir, s_name)
            if os.path.exists(candidate):
                token_path = candidate
                break
        if token_path:
            break

    sheet_logged = False
    if telemetry_broker_url and token_path and os.path.exists(token_path):
        try:
            from broker_client import load_token, report_storage_telemetry
            token = load_token(token_path)
            tab_name = config.get("STORAGE_SHEET_TAB_NAME", "Storage Monitor")
            sheet_logged, msg = report_storage_telemetry(telemetry_broker_url, token, drives, tab_name=tab_name)
            emit_log(f"Telemetry Broker: {msg}", "info" if sheet_logged else "warning", log_cb)
        except Exception as tel_err:
            emit_log(f"Notice: Storage telemetry reporting skipped: {tel_err}", "warning", log_cb)
    else:
        emit_log("Skipping Google Sheets logging: Telemetry Broker URL or token missing.", "warning", log_cb)

    # Step 3: Evaluate alert thresholds
    c_drive_gb = config.get("STORAGE_C_DRIVE_ALERT_GB", 30)
    other_pct = config.get("STORAGE_OTHER_DRIVES_ALERT_PERCENT", 90)
    critical = evaluate_drive_alerts(drives, c_drive_alert_gb=c_drive_gb, other_drives_alert_pct=other_pct)

    # Step 4: Send email alert if any drive is critical
    email_sent = False
    if critical:
        if status_cb:
            status_cb(f"⚠️ {len(critical)} drive(s) critical! Sending alert email...")
        emit_log(f"ALERT: {len(critical)} drive(s) exceeded storage threshold!", "warning", log_cb)
        for cd in critical:
            emit_log(f"  🔴 {cd['drive_letter']} — {cd['alert_reason']}", "warning", log_cb)
        email_sent = send_storage_alert_email(critical, config, log_cb=log_cb)
    else:
        emit_log("All drives within safe storage limits. No email alert needed.", "info", log_cb)

    # Build summary
    summary_parts = [
        f"Storage scan complete: {len(drives)} drive(s) scanned",
        f"Sheet logged: {'Yes' if sheet_logged else 'No'}",
        f"Critical drives: {len(critical)}",
        f"Alert sent: {'Yes' if email_sent else 'No'}"
    ]
    summary = " | ".join(summary_parts)
    emit_log(summary, "info", log_cb)
    emit_log("=" * 60, "info", log_cb)

    if status_cb:
        if critical:
            status_cb(f"⚠️ {len(critical)} drive(s) critical — Alert sent" if email_sent else f"⚠️ {len(critical)} drive(s) critical")
        else:
            status_cb("✅ All drives healthy")

    return (len(critical) == 0), summary, drives, critical


# =============================================================================
# MODULE 3: DATABASE PERFORMANCE QUERY & RE-INDEXING MAINTENANCE
# =============================================================================

def find_sqlcmd():
    """Locates sqlcmd executable across PATH and standard SQL Server paths."""
    import shutil
    p = shutil.which("sqlcmd.exe") or shutil.which("sqlcmd")
    if p:
        return p
    candidates = [
        r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\130\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files\Microsoft SQL Server\160\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files\Microsoft SQL Server\150\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files\Microsoft SQL Server\140\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files\Microsoft SQL Server\130\Tools\Binn\SQLCMD.EXE",
        r"C:\Program Files (x86)\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def execute_sql_query(sql_query, instance="localhost", timeout=600):
    """Executes a T-SQL query via sqlcmd.exe and returns (exit_code, output_text)."""
    sqlcmd = find_sqlcmd()
    if not sqlcmd:
        return 1, "sqlcmd.exe not found on system PATH or SQL installation directories."
    cmd = [sqlcmd, "-S", instance, "-E", "-Q", sql_query, "-h", "-1", "-W", "-C"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (res.stdout or res.stderr or "").strip()
        return res.returncode, out
    except subprocess.TimeoutExpired:
        return 1, f"SQL Query timed out after {timeout} seconds."
    except Exception as e:
        return 1, f"Failed to execute SQL query: {e}"


def inspect_index_fragmentation(target_db, instance="localhost", log_cb=None):
    """
    Query 1: Inspects index fragmentation across tables using sys.dm_db_index_physical_stats.
    Returns: (list_of_dict, max_fragmentation_percent)
    """
    query = f"""
SET NOCOUNT ON;
USE [{target_db}];
SELECT 
    TableName = object_name(dm.object_id),
    IndexName = i.name,
    IndexType = dm.index_type_desc,
    [%Fragmented] = CAST(avg_fragmentation_in_percent AS DECIMAL(5,2))
FROM sys.dm_db_index_physical_stats(db_id(), null, null, null, 'sampled') dm
JOIN sys.indexes i ON dm.object_id = dm.object_id AND dm.index_id = i.index_id
WHERE avg_fragmentation_in_percent > 10.0
ORDER BY avg_fragmentation_in_percent DESC;
"""
    code, out = execute_sql_query(query, instance=instance, timeout=300)
    tables = []
    max_frag = 0.0

    if code == 0 and out:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        for ln in lines:
            parts = re.split(r'\s{2,}|\t+', ln)
            if len(parts) >= 4:
                try:
                    frag_val = float(parts[3])
                except Exception:
                    frag_val = 0.0
                if frag_val > max_frag:
                    max_frag = frag_val
                tables.append({
                    "table": parts[0],
                    "index": parts[1],
                    "type": parts[2],
                    "fragmentation": frag_val
                })
            else:
                tokens = ln.split()
                if len(tokens) >= 2:
                    try:
                        frag_val = float(tokens[-1])
                        if frag_val > max_frag:
                            max_frag = frag_val
                        tables.append({
                            "table": tokens[0],
                            "index": tokens[1] if len(tokens) > 2 else "IDX",
                            "type": "INDEX",
                            "fragmentation": frag_val
                        })
                    except Exception:
                        pass
    return tables, max_frag


def run_performance_query(
    config=None,
    target_db=None,
    instance=None,
    mode="Manual",
    skip_backup=False,
    fill_factor=80,
    inspect_only=False,
    log_cb=None,
    status_cb=None,
    progress_cb=None
):
    """
    Module 3: Database Performance, Integrity & Re-indexing Suite.
    Executes:
    1. SQL Server Version & Database Size measurement
    2. Query 1: Index Fragmentation analysis
    3. Pre-maintenance safety backup
    4. Query 2: DBCC CHECKDB, DBCC DBREINDEX (FillFactor 80), sp_updatestats
    5. Post-maintenance verification
    6. Streams telemetry to Upload Broker -> Customer Sheet [Performance Query] tab
    """
    import time
    from datetime import datetime as dt

    if not config:
        config = load_config()

    target_db = target_db or config.get("DATABASE_NAME") or "master"
    instance = instance or config.get("SQL_SERVER_INSTANCE") or config.get("SQL_SERVER_NAME") or "localhost"

    start_time = dt.now()
    now_str = start_time.strftime("%Y-%m-%d %H:%M:%S")

    emit_log("=" * 60, "info", log_cb)
    emit_log("STARTING DATABASE PERFORMANCE & RE-INDEXING SUITE", "info", log_cb)
    emit_log(f"Target Database: {target_db} | Instance: {instance} | Mode: {mode}", "info", log_cb)
    emit_log(f"Task Start Time: {now_str}", "info", log_cb)
    emit_log("=" * 60, "info", log_cb)

    if progress_cb: progress_cb(0.1)
    if status_cb: status_cb("Probing SQL Server metadata and size...")

    # Step 1: Probe Version & Size
    meta_sql = f"""
SET NOCOUNT ON;
SELECT 
    CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(30)) + ' (' + CAST(SERVERPROPERTY('Edition') AS VARCHAR(40)) + ')' AS Version,
    ISNULL((SELECT SUM(size)*8/1024 FROM sys.master_files WHERE database_id = DB_ID('{target_db}')), 0) AS SizeMB;
"""
    code, meta_out = execute_sql_query(meta_sql, instance=instance)
    sql_version = "Microsoft SQL Server"
    db_size_mb = 0
    if code == 0 and meta_out:
        lines = [ln.strip() for ln in meta_out.splitlines() if ln.strip()]
        if lines:
            parts = re.split(r'\s{2,}|\t+', lines[0])
            if len(parts) >= 1: sql_version = parts[0]
            if len(parts) >= 2:
                try: db_size_mb = int(parts[1])
                except Exception: pass
    emit_log(f"SQL Server Version: {sql_version} | DB Size: {db_size_mb} MB", "info", log_cb)

    if progress_cb: progress_cb(0.25)
    if status_cb: status_cb("Executing Query 1: Index Fragmentation Analysis...")

    # Step 2: Query 1 (Index Fragmentation)
    tables_before, frag_before_max = inspect_index_fragmentation(target_db, instance=instance, log_cb=log_cb)
    frag_before_count = len(tables_before)
    emit_log(f"Query 1: {frag_before_count} indexes fragmented (>10%). Max: {frag_before_max}%", "info", log_cb)

    if inspect_only:
        if progress_cb: progress_cb(1.0)
        if status_cb: status_cb("Fragmentation analysis complete")
        return {
            "success": True,
            "target_db": target_db,
            "instance": instance,
            "sql_version": sql_version,
            "db_size_mb": db_size_mb,
            "frag_before_max": frag_before_max,
            "frag_before_count": frag_before_count,
            "tables_before": tables_before,
            "inspect_only": True,
            "summary": f"Inspected {frag_before_count} fragmented indexes. Max: {frag_before_max}%"
        }

    # Step 3: Safety Pre-Maintenance Backup
    pre_backup_status = "Skipped"
    if not skip_backup:
        if progress_cb: progress_cb(0.4)
        if status_cb: status_cb("Executing Pre-Maintenance Safety Backup...")
        emit_log("Running pre-maintenance safety backup...", "info", log_cb)
        try:
            bk_success, bk_summary = run_full_backup(config=config, log_cb=log_cb)
            if bk_success:
                pre_backup_status = "Completed & Uploaded to Drive"
                emit_log("Pre-Maintenance Safety Backup succeeded!", "info", log_cb)
            else:
                pre_backup_status = f"Warning: {bk_summary}"
                emit_log(f"Pre-backup warning: {bk_summary}", "warning", log_cb)
        except Exception as bk_err:
            pre_backup_status = f"Failed: {bk_err}"
            emit_log(f"Pre-backup error: {bk_err}", "warning", log_cb)
    else:
        emit_log("Safety backup skipped by switch.", "warning", log_cb)
        pre_backup_status = "Skipped by Flag"

    # Step 4: DBCC CHECKDB
    if progress_cb: progress_cb(0.6)
    if status_cb: status_cb("Running DBCC CHECKDB integrity validation...")
    emit_log(f"Running DBCC CHECKDB(N'{target_db}') WITH NO_INFOMSGS...", "info", log_cb)
    checkdb_sql = f"USE [{target_db}]; DBCC CHECKDB(N'{target_db}') WITH NO_INFOMSGS;"
    c_code, c_out = execute_sql_query(checkdb_sql, instance=instance, timeout=600)
    checkdb_status = "Clean (0 consistency errors)" if c_code == 0 else f"Errors: {c_out}"
    emit_log(f"CHECKDB Result: {checkdb_status}", "info" if c_code == 0 else "warning", log_cb)

    # Step 5: DBCC DBREINDEX with FillFactor
    if progress_cb: progress_cb(0.75)
    if status_cb: status_cb(f"Rebuilding table indexes (FillFactor {fill_factor})...")
    emit_log(f"Running EXEC sp_MSforeachtable DBCC DBREINDEX ('?', ' ', {fill_factor})...", "info", log_cb)
    reindex_sql = f"USE [{target_db}]; EXEC sp_MSforeachtable @command1=\"print '?' DBCC DBREINDEX ('?', ' ', {fill_factor})\";"
    r_code, r_out = execute_sql_query(reindex_sql, instance=instance, timeout=1200)
    reindex_status = f"Reindexed (FillFactor {fill_factor})" if r_code == 0 else f"Reindex Error: {r_out}"
    emit_log(f"DBREINDEX Result: {reindex_status}", "info" if r_code == 0 else "warning", log_cb)

    # Step 6: EXEC sp_updatestats
    if progress_cb: progress_cb(0.85)
    if status_cb: status_cb("Refreshing database statistics (sp_updatestats)...")
    emit_log("Running EXEC sp_updatestats...", "info", log_cb)
    stats_sql = f"USE [{target_db}]; EXEC sp_updatestats;"
    s_code, s_out = execute_sql_query(stats_sql, instance=instance, timeout=300)
    updatestats_status = "Statistics Updated" if s_code == 0 else f"Stats Warning: {s_out}"
    emit_log(f"sp_updatestats Result: {updatestats_status}", "info" if s_code == 0 else "warning", log_cb)

    # Step 7: Post-Maintenance Verification
    if progress_cb: progress_cb(0.9)
    if status_cb: status_cb("Verifying post-maintenance index fragmentation...")
    tables_after, frag_after_max = inspect_index_fragmentation(target_db, instance=instance, log_cb=log_cb)
    frag_after_count = len(tables_after)
    emit_log(f"Post-Verification: Max Fragmentation reduced: {frag_before_max}% -> {frag_after_max}%", "info", log_cb)

    duration = round((dt.now() - start_time).total_seconds(), 1)
    query_exec_time = dt.now().strftime("%Y-%m-%d %H:%M:%S")

    # Step 8: Stream metrics to Google Apps Script Broker
    if progress_cb: progress_cb(0.95)
    if status_cb: status_cb("Streaming performance metrics to Google Sheet...")
    sheet_logged = False
    broker_url = config.get("BROKER_URL") or config.get("TELEMETRY_BROKER_URL", "")
    token_path = None
    prog_data = os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData")
    for s_dir in [DATA_DIR, os.path.join(prog_data, "DatabaseBackupApp"), BASE_DIR]:
        for s_name in ["token.dpapi", "broker_token.dat"]:
            cand = os.path.join(s_dir, s_name)
            if os.path.exists(cand):
                token_path = cand
                break
        if token_path: break

    if broker_url and token_path:
        try:
            from broker_client import load_token, report_performance_telemetry
            token = load_token(token_path)
            sheet_logged, tel_msg = report_performance_telemetry(
                broker_url=broker_url,
                token=token,
                db_name=target_db,
                sql_version=sql_version,
                db_size_mb=db_size_mb,
                pre_backup_status=pre_backup_status,
                frag_before_max=frag_before_max,
                frag_after_max=frag_after_max,
                checkdb_status=checkdb_status,
                reindex_status=reindex_status,
                duration_secs=duration,
                run_mode=mode,
                task_start_time=now_str,
                query_exec_time=query_exec_time,
                status="SUCCESS" if r_code == 0 else "WARNING"
            )
            emit_log(f"Google Sheet Telemetry: {tel_msg}", "info" if sheet_logged else "warning", log_cb)
        except Exception as tel_err:
            emit_log(f"Telemetry warning: {tel_err}", "warning", log_cb)

    if progress_cb: progress_cb(1.0)
    if status_cb: status_cb("Performance & Maintenance suite complete!")

    summary = (
        f"Maintenance Completed in {duration}s | Frag: {frag_before_max}% -> {frag_after_max}% | "
        f"{checkdb_status} | {reindex_status}"
    )
    emit_log("=" * 60, "info", log_cb)
    emit_log(f"MAINTENANCE SUITE COMPLETED: {summary}", "info", log_cb)
    emit_log("=" * 60, "info", log_cb)

    return {
        "success": (r_code == 0),
        "target_db": target_db,
        "instance": instance,
        "sql_version": sql_version,
        "db_size_mb": db_size_mb,
        "pre_backup_status": pre_backup_status,
        "frag_before_max": frag_before_max,
        "frag_before_count": frag_before_count,
        "frag_after_max": frag_after_max,
        "frag_after_count": frag_after_count,
        "checkdb_status": checkdb_status,
        "reindex_status": reindex_status,
        "updatestats_status": updatestats_status,
        "duration_secs": duration,
        "sheet_logged": sheet_logged,
        "summary": summary,
        "tables_before": tables_before,
        "tables_after": tables_after
    }


