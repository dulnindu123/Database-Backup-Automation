import os
import glob
import time
import json
import logging
import gspread
import subprocess
import zipfile
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from datetime import datetime

# ================= SETUP LOGGING =================
# We set up logging immediately to catch any early errors (like missing config files)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "backup_log.txt")

logging.basicConfig(
    filename=LOG_FILE, 
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ================= LOAD CONFIG =================
def load_config():
    config_path = os.path.join(SCRIPT_DIR, "config.json")
    if not os.path.exists(config_path):
        msg = f"CRITICAL ERROR: Configuration file not found at {config_path}. Please create config.json."
        print(msg)
        logging.critical(msg)
        exit(1)
        
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            
        # Validate required fields
        required_fields = ["BACKUP_FOLDER", "BACKUP_EXTENSION", "TARGET_DATABASES", "GOOGLE_DRIVE_FOLDER_ID", "GOOGLE_SHEET_ID"]
        for field in required_fields:
            if field not in config:
                msg = f"CRITICAL ERROR: Missing '{field}' in config.json."
                print(msg)
                logging.critical(msg)
                exit(1)
                
        return config
    except json.JSONDecodeError as e:
        msg = f"CRITICAL ERROR: config.json is not a valid JSON file. Error: {e}"
        print(msg)
        logging.critical(msg)
        exit(1)
    except Exception as e:
        msg = f"CRITICAL ERROR: Failed to read config.json. Error: {e}"
        print(msg)
        logging.critical(msg)
        exit(1)

# Load configuration into global variables
CONFIG = load_config()
BACKUP_FOLDER = CONFIG["BACKUP_FOLDER"]
BACKUP_EXTENSION = CONFIG["BACKUP_EXTENSION"]
TARGET_DATABASES = CONFIG["TARGET_DATABASES"]
GOOGLE_DRIVE_FOLDER_ID = CONFIG["GOOGLE_DRIVE_FOLDER_ID"]
GOOGLE_SHEET_ID = CONFIG["GOOGLE_SHEET_ID"]
STRICTLY_MONDAYS_ONLY = CONFIG.get("STRICTLY_MONDAYS_ONLY", False)

SQL_SERVER_NAME = CONFIG.get("SQL_SERVER_NAME", "localhost\\SQLEXPRESS")
SQL_USERNAME = CONFIG.get("SQL_USERNAME", "")
SQL_PASSWORD = CONFIG.get("SQL_PASSWORD", "")

SCOPES = ["https://spreadsheets.google.com/feeds", 
          'https://www.googleapis.com/auth/spreadsheets',
          "https://www.googleapis.com/auth/drive.file", 
          "https://www.googleapis.com/auth/drive"]

def authenticate():
    creds = None
    token_path = os.path.join(SCRIPT_DIR, "token.json")
    client_secret_path = os.path.join(SCRIPT_DIR, "client_secret.json")
    
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            logging.error(f"Failed to load token.json: {e}")
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logging.info("Refreshing expired Google credentials...")
                creds.refresh(Request())
            except Exception as e:
                logging.error(f"Failed to refresh token: {e}. You may need to delete token.json and re-authenticate.")
                return None
        else:
            if not os.path.exists(client_secret_path):
                msg = f"CRITICAL ERROR: '{client_secret_path}' is missing! Required for first-time authentication."
                print(msg)
                logging.critical(msg)
                exit(1)
                
            logging.info("Starting local server for initial OAuth authentication...")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                logging.critical(f"Failed during initial OAuth authentication: {e}")
                exit(1)
            
        try:
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        except Exception as e:
            logging.error(f"Failed to save token.json: {e}. Authentication will be required again next run.")
            
    return creds

def generate_and_compress_backup(folder, db_name):
    if not os.path.exists(folder):
        msg = f"CRITICAL ERROR: The backup folder '{folder}' does not exist on this server!"
        print(msg)
        logging.critical(msg)
        return None
        
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_filename = f"{db_name}_{date_str}.bak"
    zip_filename = f"{db_name}_{date_str}.zip"
    
    bak_filepath = os.path.join(folder, bak_filename)
    zip_filepath = os.path.join(folder, zip_filename)
    
    logging.info(f"Generating SQL backup for '{db_name}' to '{bak_filepath}'...")
    
    # Build sqlcmd string
    if SQL_USERNAME and SQL_PASSWORD:
        cmd = f'sqlcmd -S "{SQL_SERVER_NAME}" -U "{SQL_USERNAME}" -P "{SQL_PASSWORD}" -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{bak_filepath}\' WITH FORMAT"'
    else:
        cmd = f'sqlcmd -S "{SQL_SERVER_NAME}" -E -Q "BACKUP DATABASE [{db_name}] TO DISK=\'{bak_filepath}\' WITH FORMAT"'
        
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(bak_filepath):
            logging.error(f"SQL Backup failed for {db_name}. Output: {result.stderr or result.stdout}")
            print(f"Error creating backup for {db_name}!")
            return None
            
        logging.info("Backup created successfully. Now compressing...")
        print(f"Backup created for {db_name}. Compressing heavily...")
        
        # Compress with Maximum Deflation
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            zipf.write(bak_filepath, arcname=bak_filename)
            
        logging.info(f"Compression complete: {zip_filepath}")
        
        # Delete the large uncompressed .bak file to save space
        if os.path.exists(zip_filepath):
            os.remove(bak_filepath)
            logging.info(f"Cleaned up temporary uncompressed file: {bak_filename}")
            
        return zip_filepath
        
    except Exception as e:
        logging.error(f"Exception during backup/compression of {db_name}: {e}")
        return None

def upload_to_google_drive(creds, file_path, folder_id, retries=3):
    file_name = os.path.basename(file_path)
    
    try:
        drive_service = build('drive', 'v3', credentials=creds)
    except Exception as e:
        logging.error(f"Failed to build Google Drive service: {e}")
        return None

    for attempt in range(1, retries + 1):
        try:
            logging.info(f"Attempt {attempt}: Uploading {file_name} to Google Drive...")
            
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            media = MediaFileUpload(file_path, resumable=True)
            
            file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            
            link = file.get('webViewLink')
            if link:
                logging.info(f"Upload successful! Google Drive Link: {link}")
                print(f"SUCCESS! {file_name} was uploaded to Google Drive!")
                
                # Make the file shareable
                try:
                    permission = {'type': 'anyone', 'role': 'reader'}
                    drive_service.permissions().create(fileId=file.get('id'), body=permission).execute()
                    logging.info("Successfully updated file permissions.")
                except Exception as perm_e:
                    logging.warning(f"File uploaded, but failed to set public permissions: {perm_e}")
                
                return link
                
        except HttpError as err:
            if err.resp.status in [403, 400] and 'quota' in str(err).lower():
                msg = f"CRITICAL ERROR: Google Drive Storage is FULL! Cannot upload {file_name}."
                print(msg)
                logging.critical(msg)
                return None
            else:
                logging.error(f"Google Drive API error: {err}")
        except Exception as e:
            logging.error(f"Network error during upload to Google Drive: {e}")
            
        if attempt < retries:
            logging.info("Retrying in 10 seconds...")
            time.sleep(10)
            
    logging.critical(f"All upload attempts failed for {file_name}.")
    return None

def update_google_sheet(creds, sheet_id, backup_filename, download_link):
    logging.info(f"Connecting to Google Sheets API to log {backup_filename}...")
    
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).sheet1
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        row = [date_str, backup_filename, download_link]
        sheet.append_row(row)
        logging.info("Successfully added row to Google Sheets.")
        print("Successfully added the link to Google Sheets!")
        return True
        
    except gspread.exceptions.APIError as api_err:
        logging.error(f"Google Sheets API Error (e.g. rate limit): {api_err}")
    except gspread.exceptions.SpreadsheetNotFound:
        msg = f"Error: Could not find a Google Sheet with ID '{sheet_id}'. Check permissions!"
        print(msg)
        logging.error(msg)
    except Exception as e:
        msg = f"Unknown Error updating sheet: {e}"
        print(msg)
        logging.error(msg)
        
    return False

if __name__ == "__main__":
    print("\nStarting Automated Google Drive Backup Workflow...")
    logging.info("=== STARTING AUTOMATED BACKUP WORKFLOW ===")
    
    if STRICTLY_MONDAYS_ONLY and datetime.today().weekday() != 0:
        print("Today is not Monday. STRICTLY_MONDAYS_ONLY is enabled in config.json. Exiting safely...")
        logging.info("Exited safely because today is not Monday.")
        exit(0)
        
    creds = authenticate()
    if not creds:
        logging.critical("Could not obtain valid Google Credentials. Exiting.")
        exit(1)
    
    for db_name in TARGET_DATABASES:
        print(f"\n--- Processing Database: {db_name} ---")
        latest_backup = generate_and_compress_backup(BACKUP_FOLDER, db_name)
        
        if latest_backup:
            file_name = os.path.basename(latest_backup)
            
            gdrive_link = upload_to_google_drive(creds, latest_backup, GOOGLE_DRIVE_FOLDER_ID)
            
            if gdrive_link:
                update_google_sheet(creds, GOOGLE_SHEET_ID, file_name, gdrive_link)
        else:
            print(f"Skipping {db_name} - No valid backup files found.")
            
    logging.info("=== WORKFLOW COMPLETE ===\n")
    print("\nWorkflow Complete. Check backup_log.txt for detailed diagnostics.")
