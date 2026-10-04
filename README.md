# Client Installation Package – Database Cloud Backup (v4.2.0)

Ready-to-ship installer and app files for the **Enterprise Database Cloud Backup & Audit Log System**.
Backups are encrypted on the customer's PC (AES-256-GCM + RSA-4096, `.dbk2` format) and uploaded through a
Google Apps Script broker to the provider's Google Drive. **No Google credentials are ever stored on the customer PC.**

> This branch contains only what is needed to install on a client machine. The admin tooling, source code and
> broker live on the `main` branch.

## Contents

| Path | Purpose |
|------|---------|
| `Setup_DatabaseBackup.exe` | The installer the customer runs |
| `AppFiles/` | The backup application (`DatabaseBackupApp.exe`, `_internal/`, public keys, blank `config.json`) |
| `Tools/decrypt_backup.py` | Admin tool to decrypt a `.dbk2` backup (needs the private key) |
| `Tools/generate_keys.py` | Admin tool to create an RSA key pair |
| `Update_App.bat` | Updates an installed app to a newer build |
| `READ_ME_FIRST.txt` | Admin quick reference |
| `sha256_manifest.json`, `build_info.json` | Build integrity and version info |

## Requirements

- Windows 10/11 or Windows Server (64-bit)
- Administrator rights
- Microsoft SQL Server reachable from the PC
- Internet access (HTTPS to `script.google.com`)

## For the Provider (Admin): preparing a customer package

Done once per customer from the `main` branch:

1. Run `python Tools\setup_new_customer.py` (one customer) or `python Tools\batch_setup_customers.py` (many).
2. Paste the printed `ENROLL_CODE` into the Google Sheet **Config** tab (A = `ENROLL_CODE`, B = the code).
3. Take the generated `customers\<slug>_package` folder. It already contains this installer, `AppFiles`,
   the customer's public keys and a signed `bundle.json`.
4. Zip it and send it to the customer.
5. Keep `customers\<slug>_keys` (private keys) **offline and never send them**.

> The `bundle.json` is customer-specific and is **not** in this branch.

## For the Customer: installing

1. Extract the ZIP you received to a normal folder (e.g. Desktop). Do not run from inside the ZIP.
2. Right-click **`Setup_DatabaseBackup.exe`** and choose **Run as administrator**.
3. The installer verifies the signed `bundle.json`, registers the PC automatically, and shows the settings screen.
4. Enter the SQL Server details, choose the backup folder and schedule, then click **Save**.
5. Done. Backups run automatically (default: Mondays at 02:00).

## Updating an installed app

Run `Update_App.bat` as administrator from the new package folder.

## Restoring a backup (provider only)

```
python Tools\decrypt_backup.py <file.dbk2> <private_key.pem> <output_file>
```
You will be asked for the key passphrase. Only the provider holds the private keys.

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| "bundle.json not found" | Make sure the whole extracted folder is kept together |
| "Signature invalid" | The package was altered or is for another installer build; request a new package |
| "PC already enrolled" (409) | This PC is already registered; contact the provider to reset it |
| Upload fails | Check internet access to `script.google.com` and that the SQL backup folder is writable |
| Installer blocked by SmartScreen | Click *More info* then *Run anyway* |

## Security notes

- Public keys only are on the client; private keys stay with the provider.
- Never commit `customers/`, `*_keys/`, or `enroll_codes*` files.
- A compromised client PC cannot list, read or delete cloud backups.

## Support

Contact your service provider with the PC name and the text of any error message.
