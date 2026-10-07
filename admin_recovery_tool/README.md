# 🛡️ Enterprise Disaster Recovery Suite (Admin Use Only)
### Zero-Trust Offline Decryption & Recovery Manual · v4.2.0

> [!CAUTION]
> **RESTRICTED TO INTERNAL ADMINISTRATORS ONLY**  
> Never deploy, distribute, or copy this directory or your offline RSA private keys (`*_private.pem`) to customer servers or client installation packages.

---

## 📌 Overview

This suite allows internal administrators to decrypt customer `.dbk2` backup archives downloaded from Google Drive.

Backups are encrypted using **Asymmetric Dual-Envelope Cryptography**:
- Data is encrypted with **AES-256-GCM** (authenticated 128-bit MAC tag).
- Ephemeral AES key is wrapped with **RSA-OAEP SHA-256** using:
  1. **Customer Primary Public Key** (`backup_public.pem`)
  2. **Admin Master Escrow Public Key** (`escrow_public.pem`)

Because client machines hold **only public keys**, customer machines can only encrypt, never decrypt. Decryption can **only** be performed on your admin workstation using either the customer's private key or your master escrow private key.

---

## 🚀 Recovery Methods

### Method 1: Graphical Recovery Wizard (1-Click)
1. Double-click **`Launch_Recovery_Wizard.bat`** (or run `python decrypt_gui.py`).
2. The modern recovery wizard opens:
   - Select the downloaded `.dbk2` file.
   - Select the corresponding offline private key (`backup_private.pem` or `escrow_private.pem`).
   - Enter your private key passphrase.
   - Choose output path (e.g., `restored_database.zip` or `.bak`).
   - Click **`[⚡ Decrypt & Verify Integrity]`**.
3. The wizard validates the header, unwraps the AES session key, checks the GCM authentication tag, verifies metadata context (Database, Host, Timestamp), and outputs the restored database dump.

---

### Method 2: Command-Line Recovery (CLI)
```bash
python decrypt_backup.py path/to/backup.dbk2 path/to/output.zip path/to/backup_private.pem
```
If your private key is password-protected, the tool securely prompts for your passphrase.

---

### Method 3: Pure PowerShell Recovery (No Python)
```powershell
powershell -ExecutionPolicy Bypass -File .\decrypt_backup.ps1 -InputFile "path\to\backup.dbk2" -OutputFile "path\to\output.zip" -PrivateKeyFile "path\to\backup_private.pem"
```

---

## 🔒 Cryptographic Invariants & Safety
- **Anti-Tampering**: If an attacker or corrupted disk flips even 1 bit in the `.dbk2` file, AES-GCM tag verification fails immediately.
- **Zero Partial Output**: If verification fails, the temporary file is immediately purged. Corrupted or malicious data is never left on disk.
- **Context Binding**: The header cryptographically binds the database name, host name, and UTC timestamp into the AES-GCM additional authenticated data (AAD). Replay attacks or cross-tenant archive swaps are mathematically detected.
