# Client Installation Package – Database Cloud Backup (v4.2.0)

Ready-to-ship installer and app files for the **Enterprise Database Cloud Backup & Audit Log System**.
Backups are encrypted on the customer's PC (AES-256-GCM + RSA-4096, `.dbk2` format) and uploaded through a
Google Apps Script broker to the provider's Google Drive. **No Google credentials are ever stored on the customer PC.**

> This branch contains only what is needed to install on a client machine. The admin tooling, source code and
> broker live on the `main` branch.

## Contents

| Path | Purpose |
|------|---------|
| `shell_client/` | **100% Native Windows PowerShell Shell Agent** (Zero Python required! Contains `install_agent.ps1`, `backup_agent.ps1`, `storage_monitor.ps1`) |
| `Setup_DatabaseBackup.exe` | Standalone graphical installer wizard |
| `AppFiles/` | GUI backup application binaries (`DatabaseBackupApp.exe`, `_internal/`, public keys, blank `config.json`) |
| `Update_App.bat` | Updates an installed app to a newer build |
| `READ_ME_FIRST.txt` | Quick reference card |
| `sha256_manifest.json`, `build_info.json` | Build integrity and version info |

> 🔒 **Decryption Security Note**: Client installation packages contain **only public keys** and cannot decrypt backups. Decryption is performed strictly by authorized service providers on an air-gapped machine using `admin_recovery_tool/` on the `main` branch.

## Requirements

- Windows 10/11 or Windows Server 2016+ (64-bit)
- Local Administrator rights
- Database engine (Microsoft SQL Server, MySQL, or PostgreSQL)
- Outbound HTTPS access (Port 443 to `script.google.com` and `drive.google.com`)
- **Python Required on Client?** **NO** — Neither the PowerShell shell agent nor the GUI executable require Python on the client machine!

---

## Installation Options

### ⚡ Option 1: Native Windows PowerShell Shell Agent (No Python Required)
Recommended for system administrators, headless servers, and locked-down environments:
1. Extract package.
2. Open an elevated PowerShell prompt (Run as Administrator):
   ```powershell
   cd shell_client
   powershell.exe -ExecutionPolicy Bypass -File .\install_agent.ps1
   ```
3. The installer auto-detects `bundle.json`, enrolls with the Apps Script broker, seals the machine token in DPAPI, and registers Windows Scheduled Tasks.
4. Test a backup immediately:
   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File .\backup_agent.ps1
   ```

### 🖥️ Option 2: Graphical Setup Wizard (`Setup_DatabaseBackup.exe`)
For desktop users preferring an interactive GUI:
1. Extract the package ZIP to a local folder.
2. Right-click **`Setup_DatabaseBackup.exe`** and choose **Run as administrator**.
3. The installer verifies the signed `bundle.json`, registers the PC automatically, and configures Scheduled Tasks.
4. Launch **DatabaseBackupApp** from the desktop shortcut to run manual backups or review live logs.

---

## Restoring a Backup (Provider / Admin Only)
Restores are performed strictly on the provider's air-gapped admin workstation using the dedicated recovery suite on the `main` branch (`admin_recovery_tool/`):
```bash
# Launch the 1-click GUI recovery wizard:
admin_recovery_tool\Launch_Recovery_Wizard.bat
```

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
