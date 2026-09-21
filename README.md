# 🚀 Enterprise Database Backup Automation

<div align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Google_Drive-4285F4?style=for-the-badge&logo=googledrive&logoColor=white" alt="Google Drive">
  <img src="https://img.shields.io/badge/Microsoft_SQL_Server-CC2927?style=for-the-badge&logo=microsoftsqlserver&logoColor=white" alt="SQL Server">
  <img src="https://img.shields.io/badge/Windows_Task_Scheduler-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Task Scheduler">
</div>

## 📌 Overview

This project is a fully autonomous, zero-touch database backup solution designed for enterprise Microsoft SQL Server environments. It replaces expensive third-party backup software with a highly optimized, native Python pipeline that compresses databases and securely uploads them to Google Drive.

Built as a robust, client-side deployment package, it guarantees seamless disaster recovery with integrated monitoring via Google Sheets.

## ✨ Key Features

- **Native SQL Extraction:** Interfaces directly with `sqlcmd` to generate high-fidelity `.bak` files.
- **Maximum Deflation Compression:** Utilizes advanced `.zip` deflation algorithms to compress backups, reducing upload payload size and saving bandwidth.
- **Automated Cloud Sync:** Seamlessly integrates with the Google Drive API (OAuth 2.0 Production Mode) to securely upload backups to off-site cloud storage.
- **Real-time Monitoring:** Logs every successful backup, file size, and timestamp into a centralized Google Sheet for easy client oversight.
- **Resilient Error Handling:** Includes custom exponential backoff logic for network interruptions and automatic quota-exceeded handling.
- **Zero-Touch Deployment:** Includes automated `.bat` scripts that instantly install dependencies and register the script as a background Windows Task.

## 🏗 Architecture

The system operates strictly within a decentralized architecture. Each client server runs the compiled Python executable securely in the background, utilizing a localized `config.json` file for modular authentication.

1. **Trigger:** Windows Task Scheduler initiates the sequence every Monday at 2:00 AM.
2. **Extraction:** Python requests a native backup from the localized SQL Server instance.
3. **Compression:** The massive `.bak` file is zipped and the original is wiped to conserve disk space.
4. **Transport:** The Google API client authenticates using a lifetime token and uploads the file.
5. **Telemetry:** The Google Sheets API records the telemetry data for system administrators.

## ⚙️ Configuration

The system uses a highly modular configuration block allowing rapid deployment across multiple different client sites:

```json
{
    "SQL_SERVER_NAME": "localhost\\SQLEXPRESS",
    "SQL_USERNAME": "",
    "SQL_PASSWORD": "",
    "TARGET_DATABASES": ["ProductionDB", "HR_Data"],
    "GOOGLE_DRIVE_FOLDER_ID": "Your-Folder-ID",
    "GOOGLE_SHEET_ID": "Your-Sheet-ID"
}
```

## 👨‍💻 Portfolio Note
*This repository serves as a showcase of my backend automation, API integration, and deployment architecture skills. Note that API keys and token credentials have been strictly omitted for security purposes.*
