# 🛡️ Enterprise Database Cloud Backup — Client Installation Package (v5.0.0)

<div align="center">
  <img src="app_icon.png" alt="Logo" width="100">
  <br>
  <p>
    <img src="https://img.shields.io/badge/Version-v5.0.0--20261104-blue?style=for-the-badge&logo=git&logoColor=white">
    <img src="https://img.shields.io/badge/Architecture-Zero--Trust%20Broker-059669?style=for-the-badge&logo=googlecloud&logoColor=white">
    <img src="https://img.shields.io/badge/Encryption-AES--256--GCM%20%2B%20RSA--4096-green?style=for-the-badge&logo=lock&logoColor=white">
    <img src="https://img.shields.io/badge/Client%20Python-NOT%20REQUIRED-success?style=for-the-badge&logo=windows&logoColor=white">
    <img src="https://img.shields.io/badge/Status-Production%20Ready-brightgreen?style=for-the-badge">
  </p>
  <h3>Autonomous, Zero-Knowledge Disaster Recovery for Microsoft SQL Server</h3>
  <p>
    <b>📄 Client Installation Guide:</b> <a href="INSTALLATION_GUIDE_v5.0.docx"><b>Download Official Word Manual (.docx)</b></a>
  </p>
</div>

---

## 📌 Overview

This branch contains the standalone **Client Installation Package (v5.0.0)** for **Enterprise Database Cloud Backup Automation**.

Database backups are generated locally on client workstations and servers, client-side encrypted with **AES-256-GCM** and enveloped with **RSA-4096**, and uploaded through a hardened Google Apps Script Zero-Trust Broker.

> 🔒 **Zero-Trust Security Guarantee**: **No Google API credentials or administrative private keys are ever stored on customer systems.** Only machine-scoped DPAPI tokens and public keys are provisioned. Decryption is mathematically impossible on the client.

---

## 📦 Package Contents

| Path | Description |
| :--- | :--- |
| **`Setup_DatabaseBackup.exe`** | One-click Graphical Setup Wizard for desktop operators |
| **`INSTALLATION_GUIDE_v5.0.docx`** | Publication-grade Microsoft Word Installation Guide |
| **`AppFiles/`** | Core desktop application (`DatabaseBackupApp.exe`, `_internal/`, preflights) |
| **`shell_client/`** | 100% Native PowerShell Shell Agent (Zero-Python, headless servers) |
| **`Update_App.bat`** | UAC Auto-elevating in-place updater for installed applications |
| **`SQLPara.txt.template`** | Externalized database credential template |
| **`Uninstall.bat`** | Clean zero-residue uninstaller |
| **`build_info.json`** | Cryptographic build manifest and version stamps |

---

## 🚀 Dual Deployment Options

### 🖥️ Option A: Graphical Setup Wizard (`Setup_DatabaseBackup.exe`)
*Best for desktop users and interactive operator environments.*
1. Extract the package ZIP to a local folder (e.g. `C:\Temp\Setup`).
2. Right-click **`Setup_DatabaseBackup.exe`** and select **Run as administrator**.
3. The wizard validates preflights, imports `bundle.json`, registers `token.dpapi`, and installs to `C:\Program Files\DatabaseBackupApp`.
4. Launch **Enterprise Database Cloud Backup** from the Desktop shortcut.

### ⚡ Option B: 100% Pure PowerShell Shell Agent (`shell_client/`)
*Best for locked-down database servers, headless Windows Server Core, and legacy systems.*
* **Zero Python required, Zero external .EXE binaries.**
* Footprint under 30 KB.
1. Open PowerShell as Administrator.
2. Navigate to `shell_client`:
   ```powershell
   cd shell_client
   powershell.exe -ExecutionPolicy Bypass -File .\install_agent.ps1
   ```
3. Test a backup immediately:
   ```powershell
   powershell.exe -ExecutionPolicy Bypass -File .\backup_agent.ps1
   ```

---

## 🛠️ In-Place Upgrade / Patching
If an older version is already installed on the machine, right-click **`Update_App.bat`** and select **Run as administrator**. It preserves existing database configurations while upgrading binaries, ACLs, and scheduled tasks in under 10 seconds.

---

## 📄 Documentation
Comprehensive installation steps, pre-requisites, SQL Server configuration, and troubleshooting are detailed in the official Microsoft Word manual:
👉 [**INSTALLATION_GUIDE_v5.0.docx**](INSTALLATION_GUIDE_v5.0.docx)
