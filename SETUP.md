# Secure backup: setup and test guide

Architecture: **PC app -> broker (Cloud Run) -> locked GCS bucket.** The PC holds no Google credentials.
Its two secrets are a broker token (can only *request an upload slot*) and a *public* encryption key (can only *encrypt*).

## What changed in your code
| File | Change |
|---|---|
| `backup_core.py` | Drive/Sheets upload replaced by encrypt -> broker upload -> MD5 verify. `shell=True` removed (SQL + icacls). DB-name/path validation. ACL no longer grants Everyone. SQL password goes via env var, not the command line. OAuth scope reduced to Sheets only. |
| `auto_backup.py` | Uses `broker_ready()` instead of Google OAuth. |
| `backup_core.py` | Drive/Sheets upload replaced by encrypt -> broker upload -> MD5 verify. `shell=True` removed (SQL + icacls). DB-name/path validation. ACL no longer grants Everyone. SQL password goes via env var, not the command line. OAuth scope reduced to Sheets only. |
| `auto_backup.py` | Uses `broker_ready()` instead of Google OAuth. |
| `build_executable.bat` | No longer ships `client_secret.json`/`token.json`; bundles `backup_public.pem` and `escrow_public.pem`. |
| `installer_gui.py` | Upgrade-preserve list now keeps `broker_token.dat`, `backup_public.pem`, and `escrow_public.pem`. |
| NEW `crypto_stream.py`, `broker_client.py` | Streaming DBK2 encryption; broker client with resume + integrity check. |
| NEW `broker/`, `offline/` | The broker service; key generation and restore tools. |

`pip install cryptography requests pywin32` (add to `requirements.txt`).

## Step 0: Rotate leaked secrets (do first)
- Delete service-account key `9469dce8...` in project `backupbot-506604`; delete/reset the OAuth client secret in `backupsystem-509315`.
- Anything already installed from old builds still contains the old `client_secret.json`. Rotating makes those useless.
- Old `token.json` files on PCs hold Drive access: revoke at https://myaccount.google.com/permissions.

## Step 1: Keys (offline workstation, once)
```
cd offline && python generate_keys.py
```
This generates:
- `backup_public.pem` & `backup_private.pem` (Primary RSA-4096 keypair)
- `escrow_public.pem` & `escrow_private.pem` (Escrow RSA-4096 keypair for emergency recovery)

Keep `backup_private.pem` and `escrow_private.pem` + passphrases offline in **two air-gapped locations**. Give only the public keys (`backup_public.pem` and `escrow_public.pem`) to the app installer.

## Step 2: Bucket (start with an UNLOCKED retention while testing)
```
PROJECT=your-project ; BUCKET=your-org-db-backups ; REGION=asia-south1
gcloud config set project $PROJECT
gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://$BUCKET --retention-period=30d          # TEST value, unlocked initially
gcloud storage buckets update gs://$BUCKET --versioning                    # optional extra safety
gcloud storage buckets update gs://$BUCKET --lifecycle-file=lifecycle.json  # delete after 35d (see below)
```
`lifecycle.json`: `{"rule":[{"action":{"type":"Delete"},"condition":{"age":35}}]}` (lifecycle can only delete after retention has expired).

## Step 3: Broker
```
gcloud iam service-accounts create upload-broker
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member=serviceAccount:upload-broker@$PROJECT.iam.gserviceaccount.com --role=roles/storage.objectCreator

cd admin
python provision_pc.py --pc-id pc-office-01
# 1. Generates 'raw_token.txt' for secure transfer to the client PC
# 2. Prints SHA-256 hash snippet to add to pc_tokens.json
gcloud secrets create pc-tokens --data-file=pc_tokens.json
gcloud secrets add-iam-policy-binding pc-tokens \
  --member=serviceAccount:upload-broker@$PROJECT.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor

cd ../broker
gcloud run deploy upload-broker --source . --region $REGION --allow-unauthenticated \
  --service-account upload-broker@$PROJECT.iam.gserviceaccount.com \
  --set-env-vars BUCKET=$BUCKET,ALLOWED_DBS=UserDB,RGT,MAX_BYTES=107374182400,TOKENS_FILE=/secrets/pc_tokens.json \
  --set-secrets /secrets/pc_tokens.json=pc-tokens:latest --max-instances 10
```
`--allow-unauthenticated` is intentional: the per-PC Bearer token is the auth.
**Revoke a PC:** delete its entry from `pc_tokens.json`, then upload the new secret version: `gcloud secrets versions add pc-tokens --data-file=pc_tokens.json`.
Note: Revocation takes a few minutes to propagate across Cloud Run instances as the mounted secret volume refreshes.

## Step 4: Token Provisioning & PC Configuration
`config.json` add: `"BROKER_URL": "https://upload-broker-xxxx.run.app"`.

**CRITICAL (DPAPI Machine Binding):**
Windows DPAPI tokens are tied to the local machine's LSA secrets and cannot be moved between machines.
1. Transfer `raw_token.txt` securely from the admin machine to the customer PC (e.g. encrypted admin USB, SCP/WinSCP).
2. Place `raw_token.txt` in the installer directory next to `1_Quick_Install.bat` or `Update_App.bat`.
3. Run the installer script. It encrypts the token locally into `broker_token.dat` using `CryptProtectData` (machine scope), and immediately overwrites and deletes `raw_token.txt`.
4. Apply Admin-only write ACLs: `icacls "C:\Program Files\DatabaseBackupApp" /grant:r Administrators:(OI)(CI)F /grant:r Users:(OI)(CI)RX`.

## Step 5: Verification & Tests (all must pass before locking)
1. Backup runs end to end; object appears at `pc-office-01/<DB>/<date>_1.dbk2`.
2. **Restore drill:** download the `.dbk2` file, run offline decryption:
   ```bash
   python offline/decrypt_backup.py backup_20261001_1.dbk2 out.zip backup_private.pem [password]
   ```
   Verify with `escrow_private.pem` as well.
3. **Upload Slot Rules:** Run backup twice in a day: 1st occupies `_1.dbk2`, 2nd occupies `_2.dbk2`, 3rd occupies `_3.dbk2`. A 4th attempt receives HTTP 409 Conflict.
4. **Slot-Burning Threat & Mitigation:** If a token is stolen, an attacker can consume the 3 daily slots. The client logs warnings on 409 and raises a critical security alert if all 3 slots are exhausted. To mitigate, revoke the token in Secret Manager, re-provision a new token, and securely re-deploy to the PC.
5. Try to delete the object with the *broker's* identity: fails (broker has `roles/storage.objectCreator` only, no delete permission).
6. Delete a token line in `pc_tokens.json` -> that PC gets 401 within a few minutes.
7. Confirm folder ACL: `icacls` shows only Administrators have Full Control, standard users have Read/Execute.

## Step 6: Lock Retention (Irreversible)
Only after every test passes and you are confident in retention duration:
```
gcloud storage buckets update gs://$BUCKET --retention-period=30d
gcloud storage buckets update gs://$BUCKET --lock-retention-period
```
Once locked, nobody (including Google Cloud project owners) can delete objects or reduce retention until the retention duration expires.
