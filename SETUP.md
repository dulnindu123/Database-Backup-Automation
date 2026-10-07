# Secure backup: setup and test guide

> [!NOTE]
> **Production Architecture (v4.2.0)**: The live production system operates on the **Zero-Billing Google Apps Script Broker** (`apps_script_broker/Code.gs`), Google Drive, and Google Sheets. For active setup instructions, see [`README.md`](README.md), [`USER_GUIDE.md`](USER_GUIDE.md), and [`CODE_REVIEW.md`](CODE_REVIEW.md).


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

## Step 3: Customer Onboarding (Automated Per-Customer Broker)
Use the automated customer onboarding engine on your administrator workstation:
```bash
python admin/onboard_customer.py --customer <slug> --project $PROJECT --region $REGION --bucket $BUCKET
```
This single command automates the entire cloud and package provisioning lifecycle:
1. Validates the customer slug (2-24 lowercase alphanumerics, e.g. `acme`).
2. Creates dedicated service account `broker-<slug>@$PROJECT.iam.gserviceaccount.com`.
3. Creates Secret Manager secret `broker-tokens-<slug>` with SHA-256 token hash for `<slug>-pc01`.
4. Binds IAM-conditioned `roles/storage.objectCreator` on `gs://$BUCKET` restricted strictly to `projects/_/buckets/$BUCKET/objects/<slug>/`.
5. Deploys dedicated Cloud Run microservice `broker-<slug>` with `--min-instances=0`, `--max-instances=2`, `CUSTOMER_SLUG=<slug>`, and per-customer `MAX_BYTES`.
6. Probes `/healthz` on the deployed URL to verify liveness.
7. Digitally signs `manifest.json` using the administrator Ed25519 private key (kept strictly off customer PCs).
8. Builds the customer installation bundle in `dist/Customer_Packages/<slug>/`.
9. Records service name, URL, and metadata in `admin/customer_registry.json`.

**Fleet Management & Rollouts:**
- Roll a new container image across all provisioned customer microservices:
  ```bash
  python admin/release_all.py --image us-central1-docker.pkg.dev/$PROJECT/backup-broker/upload-broker:v4.2.0
  ```
- Offboard a customer and de-provision all cloud resources (deletes Cloud Run service, secret, service account, bucket IAM binding, package, and registry record):
  ```bash
  python admin/offboard_customer.py --customer <slug>
  ```

## Step 4: Customer PC Installation (Zero Typing Required)
Deliver the tailored package from `dist/Customer_Packages/<slug>/` to the customer PC:
1. The customer runs `Setup_DatabaseBackup.exe` as Administrator.
2. The installer automatically validates the Ed25519 signature on `manifest.json` against the embedded administrator public key.
3. The customer types nothing:
   - Unique broker URL is pre-loaded and locked (`state="disabled"`).
   - Machine token is extracted from the signed manifest and sealed into Windows DPAPI machine storage (`token.dpapi`).
4. If an attacker modifies the manifest or tamper with binaries, the installer detects the tampering (`ERR_MANIFEST_TAMPERED`), displays a red alert banner, and halts setup.

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
