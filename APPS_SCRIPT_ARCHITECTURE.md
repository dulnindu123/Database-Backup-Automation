# Apps Script Zero-Billing Drive Architecture

## Exact Manual Deployment Steps

1. **Create the Project:**
   - Go to [script.google.com](https://script.google.com).
   - Click **New project**.
   - Rename the project (e.g., "Backup Upload Broker").

2. **Paste the Code:**
   - Replace the contents of `Code.gs` with the code from `apps_script_broker/Code.gs`.
   - In the Apps Script editor, click the **Settings** gear icon on the left.
   - Check the box for **"Show 'appsscript.json' manifest file in editor"**.
   - Go back to the `< > Editor`. Select `appsscript.json` and replace its contents with the code from `apps_script_broker/appsscript.json`.

3. **Configure Google Sheet & Drive Folder:**
   - Create a new Google Sheet. Name it "Backup Data".
   - Create 4 tabs exactly named: `Config`, `Tokens`, `Audit`, `Telemetry`.
   - In the `Config` tab, put `ENROLL_CODE` in cell A2, and your secret code (e.g., `SECRET123`) in cell B2.
   - Note the Spreadsheet ID from the URL (`https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit`).
   - Create a Google Drive folder for backups. Note its ID from the URL (`https://drive.google.com/drive/folders/THIS_IS_THE_ID`).
   - Update line 2 and 3 in `Code.gs` with these IDs.

4. **Deploy as Web App:**
   - Click the blue **Deploy** button > **New deployment**.
   - Select type: **Web app**.
   - Description: "v1 Production".
   - **Execute as:** `Me (your_email@gmail.com)` *(Crucial: This is what allows anonymous clients to upload to your drive)*
   - **Who has access:** `Anyone`
   - Click **Deploy**.
   - You will be prompted to "Authorize access". Proceed through the warnings ("Advanced > Go to Backup Upload Broker (unsafe)").
   - Copy the resulting **Web app URL**. This is your new `BROKER_URL`.

---

## Honest Risk & Quota Assessment

By bypassing Google Cloud Run and relying exclusively on a free personal/Workspace Google Drive and Apps Script, you are accepting the following trade-offs:

### 1. No Deletion Lock (Ransomware Vulnerability)
**Google Drive does not support Object Retention Locks (WORM).**
In the Google Cloud Storage design, a cryptographically enforced policy prevented *anyone* (even the project owner) from deleting a backup before 30 days. In this Drive architecture, if an attacker gains access to your primary Google Account (the one executing the Apps Script), they can instantly empty the trash and delete all customer backups. **The single-account risk is extreme.** 

### 2. Apps Script Execution Limits (Quotas)
Apps Script is a free sandbox and is subject to strict daily quotas:
- **URL Fetch calls:** 20,000 / day (Google Workspace) or 20,000 / day (Consumer). You make 1 fetch per upload request. 
- **Script runtime:** 6 min / execution, 6 hours / day total. (Our `doPost` is very fast, but if 100 PCs hit it exactly at the same time, you may exhaust the daily runtime).
- **Simultaneous Executions:** Maximum 30 concurrent executions. If 31 PCs ping at the exact same millisecond, the 31st receives a 429 error.

### 3. Drive API Upload Limits
- Individual users are limited to **750 GB of uploads per day** across all Drive API usage. 
- If 100 customers are uploading 10 GB each, that is 1,000 GB/day. **Your account will be temporarily banned from uploading for 24 hours.** You must carefully monitor backup sizes to stay under 750 GB/day.

### 4. Unverified Behaviors
- **UrlFetchApp Location Header Case Sensitivity:** Some APIs return `Location`, others `location`. The code checks both, but Apps Script's specific HTTP client handling of resumable session creation via POST without following redirects could not be definitively verified without live endpoint testing.
- **Drive Resumable Upload Expiration:** Drive resumable session URIs typically expire after 1 week, which is fine, but chunked uploads via HTTP PUT with `Content-Range` must strictly adhere to 256 KiB multiples.

---

## The Restore Procedure (Pull-Based Second Copy)

Since the broker holds no credentials to read backups (Zero-Trust), you must pull backups down manually or via an isolated script on an admin machine.

We have created `pull_backup.py`. You will run this on a separate, highly secure administrative PC. 
1. It logs in using a completely separate `READ-ONLY` Google Drive OAuth scope.
2. It fetches `.dbk2` files.
3. You run the air-gapped `decrypt_backup.py` with the private key to restore.
