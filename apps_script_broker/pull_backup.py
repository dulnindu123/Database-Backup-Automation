"""
Script to pull backups from the Apps Script Google Drive Storage 
to a separate administrative machine securely.
Requires a Google Cloud project with Google Drive API enabled,
and a Service Account or OAuth credentials with READONLY Drive scope.
"""
import os
import io
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Only Read-Only access to Drive is needed
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'drive_readonly_service_account.json'
DRIVE_FOLDER_ID = 'YOUR_DRIVE_FOLDER_ID_HERE'
DOWNLOAD_DIR = './downloaded_backups'

def get_drive_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"Missing {SERVICE_ACCOUNT_FILE}")
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def download_file(service, file_id, file_name):
    print(f"Downloading {file_name}...")
    request = service.files().get_media(fileId=file_id)
    fh = io.FileIO(os.path.join(DOWNLOAD_DIR, file_name), 'wb')
    downloader = MediaIoBaseDownload(fh, request, chunksize=8*1024*1024)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        if status:
            print(f"Download {int(status.progress() * 100)}%.")
    print(f"Download complete: {file_name}")

def sync_backups():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    service = get_drive_service()

    # Find all .dbk2 files in the folder (or subfolders if desired)
    query = f"'{DRIVE_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"
    
    print("Querying Drive for new backups...")
    results = service.files().list(q=query, spaces='drive', fields='files(id, name, md5Checksum)').execute()
    files = results.get('files', [])

    if not files:
        print("No files found.")
        return

    for f in files:
        file_path = os.path.join(DOWNLOAD_DIR, f['name'])
        if os.path.exists(file_path):
            print(f"Skipping {f['name']}, already exists.")
            # Note: could compare md5Checksum here if paranoid
            continue
        try:
            download_file(service, f['id'], f['name'])
        except Exception as e:
            print(f"Error downloading {f['name']}: {e}")

if __name__ == '__main__':
    sync_backups()
