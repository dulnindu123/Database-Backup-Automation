import os
import sys
import glob
import time
import json
import logging
import zipfile
import subprocess
from datetime import datetime

# Google APIs
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Allow OAuth scope relaxation (prevents ScopeChangedError when Google adjusts/condenses scopes)
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# Protect against None stdout/stderr in windowed/noconsole executables
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets"
]

TASK_SCHEDULER_NAME = "Database Cloud Backup"



def get_base_dir():
    """Return the persistent directory where config, logs, and tokens reside."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundled executable
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
LOG_FILE = os.path.join(BASE_DIR, "backup_log.txt")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")

# Configure root logger
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def emit_log(message, level="info", log_cb=None):
    """Log to file and forward to UI callback if provided."""
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {message}"
    
    if level == "critical":
        logging.critical(message)
    elif level == "error":
        logging.error(message)
    elif level == "warning":
        logging.warning(message)
    else:
        logging.info(message)
        
    print(formatted)
    if log_cb:
        try:
            log_cb(formatted, level)
        except Exception:
            pass

def load_config():
    """Load configuration from config.json or return safe defaults."""
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
        "SCHEDULE_TIME": "02:00"
    }
    
    if not os.path.exists(CONFIG_FILE):
        emit_log(f"config.json not found at {CONFIG_FILE}. Creating with defaults.", "warning")
        save_config(default_config)
        return default_config
        
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Merge with default keys in case any are missing
            for k, v in default_config.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception as e:
        emit_log(f"Failed to load config.json: {e}", "error")
        return default_config

def save_config(config_data):
    """Save configuration dictionary to config.json."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
        emit_log("Configuration saved successfully.")
        return True, "Configuration saved successfully."
    except Exception as e:
        err = f"Failed to save configuration: {e}"
        emit_log(err, "error")
        return False, err

def authenticate(interactive=True, log_cb=None):
    """Authenticate with Google OAuth2."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            emit_log(f"Failed to load token.json: {e}", "warning", log_cb)
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                emit_log("Refreshing expired Google credentials...", "info", log_cb)
                creds.refresh(Request())
            except Exception as e:
                emit_log(f"Failed to refresh token: {e}", "error", log_cb)
                creds = None
                
        if not creds:
            if not os.path.exists(CLIENT_SECRET_FILE):
                emit_log(f"client_secret.json missing at {CLIENT_SECRET_FILE}", "critical", log_cb)
                return None
                
            if not interactive:
                emit_log("Interactive authentication needed but running in non-interactive mode.", "error", log_cb)
                return None
                
            emit_log("Starting browser OAuth flow for Google authentication...", "info", log_cb)
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                emit_log(f"OAuth authentication failed: {e}", "critical", log_cb)
                return None
                
        # Save valid token
        try:
            with open(TOKEN_FILE, 'w', encoding='utf-8') as token:
                token.write(creds.to_json())
            emit_log("Google credentials stored in token.json", "info", log_cb)
        except Exception as e:
            emit_log(f"Failed to save token.json: {e}", "warning", log_cb)
            
    return creds

def reset_credentials():
    """Remove stored token.json to allow signing in with a different Google account."""
    if os.path.exists(TOKEN_FILE):
        try:
            os.remove(TOKEN_FILE)
            emit_log("Removed stored credentials (token.json).")
            return True, "Stored credentials removed. You can now sign in with a different Google account."
        except Exception as e:
            err = f"Failed to delete token.json: {e}"
            emit_log(err, "error")
            return False, err
    return True, "No stored credentials found."


def test_google_connection(creds, drive_folder_id, sheet_id, log_cb=None):
    """Test connectivity to Google Drive and Google Sheets."""
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
    
    # Test Drive
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        folder = drive_service.files().get(fileId=drive_folder_id, fields='name').execute()
        results["drive"] = True
        results["drive_name"] = folder.get('name', 'Unknown')
        emit_log(f"Google Drive verified. Folder: '{results['drive_name']}'", "info", log_cb)
    except Exception as e:
        results["errors"].append(f"Google Drive error: {e}")
        emit_log(f"Google Drive connection failed: {e}", "error", log_cb)
        
    # Test Sheets
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        results["sheet"] = True
        results["sheet_title"] = sheet.title
        emit_log(f"Google Sheets verified. Worksheet: '{sheet.title}'", "info", log_cb)
    except Exception as e:
        results["errors"].append(f"Google Sheets error: {e}")
        emit_log(f"Google Sheets connection failed: {e}", "error", log_cb)
        
    return results

def generate_and_compress_backup(folder, db_name, sql_server, sql_user="", sql_password="", log_cb=None):
    """Create a SQL Server database backup (.bak) and compress it (.zip)."""
    if not os.path.exists(folder):
        try:
            os.makedirs(folder, exist_ok=True)
            emit_log(f"Created backup directory: {folder}", "info", log_cb)
        except Exception as e:
            emit_log(f"Backup folder does not exist and could not be created: {e}", "critical", log_cb)
            return None
            
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_filename = f"{db_name}_{date_str}.bak"
    zip_filename = f"{db_name}_{date_str}.zip"
    bak_filepath = os.path.join(folder, bak_filename)
    zip_filepath = os.path.join(folder, zip_filename)
    
    emit_log(f"Initiating SQL backup for database '{db_name}'...", "info", log_cb)
    
    if sql_user and sql_password:
        cmd = f'sqlcmd -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{bak_filepath}\' WITH FORMAT"'
    else:
        cmd = f'sqlcmd -S "{sql_server}" -E -C -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{bak_filepath}\' WITH FORMAT"'

        
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(bak_filepath):
            err_msg = result.stderr or result.stdout
            emit_log(f"SQL Backup failed for {db_name}: {err_msg}", "error", log_cb)
            return None
            
        emit_log(f"Database backup created: {bak_filename}. Compressing with max deflation...", "info", log_cb)
        
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            zipf.write(bak_filepath, arcname=bak_filename)
            
        # Clean up temporary .bak
        if os.path.exists(zip_filepath):
            os.remove(bak_filepath)
            size_mb = os.path.getsize(zip_filepath) / (1024 * 1024)
            emit_log(f"Compressed {zip_filename} ({size_mb:.2f} MB). Temporary .bak removed.", "info", log_cb)
            
        return zip_filepath
    except Exception as e:
        emit_log(f"Backup/compression error for {db_name}: {e}", "error", log_cb)
        return None

def upload_to_google_drive(creds, file_path, folder_id, retries=3, log_cb=None):
    """Upload a backup file to Google Drive and return its viewable web link."""
    file_name = os.path.basename(file_path)
    try:
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception as e:
        emit_log(f"Google Drive service build failure: {e}", "error", log_cb)
        return None
        
    for attempt in range(1, retries + 1):
        try:
            emit_log(f"Uploading {file_name} to Google Drive (Attempt {attempt}/{retries})...", "info", log_cb)
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            media = MediaFileUpload(file_path, resumable=True)
            uploaded_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            file_id = uploaded_file.get('id')
            link = uploaded_file.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
            if link:
                emit_log(f"Upload complete for {file_name}! Link: {link}", "info", log_cb)
                # Attempt to set public read permission
                try:
                    permission = {'type': 'anyone', 'role': 'reader'}
                    drive_service.permissions().create(fileId=file_id, body=permission).execute()
                    emit_log(f"Permissions set: Link is accessible.", "info", log_cb)
                except Exception as perm_err:
                    emit_log(f"Public permission notice: {perm_err}", "warning", log_cb)
                return link

        except HttpError as err:
            if err.resp.status in [400, 403] and 'quota' in str(err).lower():
                emit_log(f"CRITICAL: Google Drive storage quota full! {err}", "critical", log_cb)
                return None
            emit_log(f"Google Drive API error: {err}", "error", log_cb)
        except Exception as e:
            emit_log(f"Network error during upload: {e}", "error", log_cb)
            
        if attempt < retries:
            emit_log("Retrying upload in 10 seconds...", "info", log_cb)
            time.sleep(10)
            
    emit_log(f"Upload failed after {retries} attempts for {file_name}.", "critical", log_cb)
    return None

def format_file_size(size_bytes):
    """Format bytes into readable string (e.g. 550 KB, 455.20 MB, 1.25 GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

def update_google_sheet(creds, sheet_id, backup_filename, file_size_str, download_link, log_cb=None):
    """Log the successful backup into Google Sheets including File Size."""
    emit_log(f"Logging backup to Google Sheet ({backup_filename}, {file_size_str})...", "info", log_cb)
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        
        # Ensure header row exists
        first_row = sheet.row_values(1)
        headers = ["Date & Time", "Backup File Name", "File Size", "Google Drive Download Link"]
        if not first_row or "Date" not in first_row[0]:
            sheet.insert_row(headers, index=1)
            emit_log("Created header row in Google Sheet.", "info", log_cb)
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp, backup_filename, file_size_str, download_link]
        sheet.append_row(row)
        emit_log(f"Google Sheet updated with entry: {backup_filename} ({file_size_str})", "info", log_cb)
        return True
    except Exception as e:
        emit_log(f"Google Sheets logging error: {e}", "error", log_cb)
        return False

def run_full_backup(config=None, log_cb=None, progress_cb=None, status_cb=None):
    """Executes the complete backup cycle for all configured databases."""
    if not config:
        config = load_config()
        
    emit_log("=" * 60, "info", log_cb)
    emit_log("STARTING BACKUP EXECUTION CYCLE", "info", log_cb)
    emit_log("=" * 60, "info", log_cb)
    
    if status_cb:
        status_cb("Authenticating with Google...")
    if progress_cb:
        progress_cb(0.1)
        
    creds = authenticate(interactive=True, log_cb=log_cb)
    if not creds:
        emit_log("Authentication failed. Aborting backup cycle.", "critical", log_cb)
        if status_cb:
            status_cb("Authentication Failed")
        return False, "Google Authentication Failed"
        
    databases = config.get("TARGET_DATABASES", [])
    if not databases:
        emit_log("No target databases specified in configuration.", "warning", log_cb)
        return True, "No databases configured."
        
    total_dbs = len(databases)
    success_count = 0
    
    for idx, db_name in enumerate(databases):
        step_progress = 0.15 + (idx / total_dbs) * 0.8
        if progress_cb:
            progress_cb(step_progress)
        if status_cb:
            status_cb(f"Processing database {idx + 1}/{total_dbs}: {db_name}")
            
        emit_log(f"--- Processing Database: {db_name} ---", "info", log_cb)
        
        backup_zip = generate_and_compress_backup(
            folder=config.get("BACKUP_FOLDER", "C:\\temp\\backups"),
            db_name=db_name,
            sql_server=config.get("SQL_SERVER_NAME", "localhost\\SQLEXPRESS"),
            sql_user=config.get("SQL_USERNAME", ""),
            sql_password=config.get("SQL_PASSWORD", ""),
            log_cb=log_cb
        )
        
        if backup_zip and os.path.exists(backup_zip):
            file_name = os.path.basename(backup_zip)
            file_size_bytes = os.path.getsize(backup_zip)
            file_size_str = format_file_size(file_size_bytes)
            
            if status_cb:
                status_cb(f"Uploading {file_name} ({file_size_str}) to Google Drive...")
            link = upload_to_google_drive(
                creds=creds,
                file_path=backup_zip,
                folder_id=config.get("GOOGLE_DRIVE_FOLDER_ID"),
                log_cb=log_cb
            )
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
            else:
                emit_log(f"Upload failed for {db_name}.", "error", log_cb)
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

# ================= TASK SCHEDULER HELPERS =================
def get_scheduler_status(task_name=TASK_SCHEDULER_NAME):
    """Check if the Windows Task Scheduler entry exists and is active."""
    try:
        cmd = f'schtasks /query /tn "{task_name}" /fo CSV /nh'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0 and task_name in res.stdout:
            # Parse status
            status_line = res.stdout.strip().split("\n")[0]
            parts = [p.strip('"\r') for p in status_line.split('","')]
            status = parts[2] if len(parts) > 2 else "Scheduled"
            next_run = parts[1] if len(parts) > 1 else "Unknown"
            return True, f"Active ({status}) - Next Run: {next_run}"
        return False, "Not Scheduled"
    except Exception as e:
        return False, f"Error: {e}"

def enable_scheduler(executable_path=None, day="MON", time_str="02:00", task_name=TASK_SCHEDULER_NAME):
    """Configure Windows Task Scheduler to run the app weekly with --auto."""
    if not executable_path:
        if getattr(sys, 'frozen', False):
            executable_path = sys.executable
        else:
            executable_path = f'python "{os.path.join(BASE_DIR, "auto_backup.py")}"'
            
    # Wrap executable in quotes and append --auto
    if executable_path.startswith("python "):
        cmd_run = f'{executable_path} --auto'
    else:
        cmd_run = f'\\"{executable_path}\\" --auto'
        
    cmd = f'schtasks /create /tn "{task_name}" /tr "{cmd_run}" /sc weekly /d {day} /st {time_str} /f'
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            emit_log(f"Scheduled task '{task_name}' created successfully (Every {day} at {time_str}).")
            return True, f"Scheduled successfully: Every {day} at {time_str}."
        else:
            err = res.stderr or res.stdout
            emit_log(f"Failed to create scheduled task: {err}", "error")
            return False, f"Scheduler error: {err}"
    except Exception as e:
        return False, str(e)

def disable_scheduler(task_name=TASK_SCHEDULER_NAME):
    """Remove the task from Windows Task Scheduler."""
    cmd = f'schtasks /delete /tn "{task_name}" /f'
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            emit_log(f"Scheduled task '{task_name}' removed.")
            return True, "Task Scheduler schedule removed."
        else:
            return False, res.stderr or res.stdout
    except Exception as e:
        return False, str(e)

def detect_sql_server_instances():
    """Detect local SQL Server instances from Windows registry and services."""
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
    """Query SQL Server for all non-system databases."""
    if sql_user and sql_password:
        cmd = f'sqlcmd -S "{sql_server}" -U "{sql_user}" -P "{sql_password}" -C -h -1 -W -Q "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE database_id > 4"'
    else:
        cmd = f'sqlcmd -S "{sql_server}" -E -C -h -1 -W -Q "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE database_id > 4"'
        
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip() and not line.startswith("---")]
    except Exception:
        pass
    return []

