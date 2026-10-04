================================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & AUDIT LOG SYSTEM (Zero-Trust v4.2.0)
  Administrator Provisioning & Deployment Quick Reference
================================================================================

Welcome to the Enterprise Database Cloud Backup system. This package delivers 
an air-gapped, zero-trust disaster recovery solution. Backups are encrypted 
with AES-256-GCM + RSA-4096 (DBK2 format) and securely uploaded via a Google 
Apps Script Web App Broker to a retention-locked Google Drive.

--------------------------------------------------------------------------------
ZERO-TRUST SECURITY ARCHITECTURE:
--------------------------------------------------------------------------------
- ZERO Google Credentials on Client PCs: A compromised client cannot read, list, 
  or delete any backup files stored in the cloud.
- Air-Gapped Keypairs: Backups are encrypted locally using public keys. 
  Private decryption keys remain strictly offline on admin hardware.
- Zero-Typing Installation: The customer executes the installer, and it securely
  authenticates using a cryptographic bundle signed by the Admin. No typing required!

--------------------------------------------------------------------------------
HOW TO PROVISION A NEW CUSTOMER (ADMINISTRATOR SETUP):
--------------------------------------------------------------------------------
We have fully automated the setup process with an Easy Setup Wizard. You only
need to run this once per customer.

1. INITIAL GOOGLE SHEET SETUP (One-time only)
   - Ensure your Google Apps Script (`apps_script_broker/Code.gs`) is deployed
     as a Web App.
   - Keep your Google Apps Script URL handy.

2. RUN THE SETUP WIZARD
   - Open a terminal in the `BackupAutomation` folder.
   - Run: `python Tools\setup_new_customer.py`
   - The wizard will ask for:
     * Customer Slug (e.g. 'acme')
     * Your Apps Script URL
     * A strong passphrase for the new customer's keys
     * Your Admin Signing Key (it will help you create one if you don't have one)

3. UPDATE THE GOOGLE SHEET
   - The script will output a success message and an `ENROLL_CODE`.
   - Open your Google Sheet, go to the "Config" tab.
   - Paste the `ENROLL_CODE` into the cell next to "ENROLL_CODE".

4. SEND THE PACKAGE TO THE CUSTOMER
   - The script automatically generated a complete, ready-to-send folder located at:
     `BackupAutomation\customers\<slug>_package`
   - Zip this folder and send it to your customer. 
   - (Keep the `_keys` folder safely offline!)

--------------------------------------------------------------------------------
CUSTOMER EXPERIENCE (INSTALLATION):
--------------------------------------------------------------------------------
1. The customer extracts the ZIP file you sent them.
2. They Right-Click `Setup_DatabaseBackup.exe` and choose "Run as Administrator".
3. The installer detects the `bundle.json`, verifies your Admin signature, and 
   automatically grabs their PC name and securely registers it with your Google Sheet.
4. They simply select their backup folder and click "Save". Zero typing!

================================================================================
