"""
create_claude_audit_bundle.py
=============================================================================
Generates a complete, ready-to-audit package for Claude:
1. claude_failproof_audit_pack.zip (clean zip of all core source files, 0 binaries).
2. CLAUDE_FAILPROOF_AUDIT_DOSSIER.md (single self-contained dossier with adversarial prompt & code).
"""
import os
import zipfile

BASE_DIR = r"c:\Users\dulni\OneDrive\Documents\Desktop\idea\BackupAutomation"
OUTPUT_DIR = r"c:\Users\dulni\OneDrive\Documents\Desktop\idea"

AUDIT_FILES = [
    # 1. Cloud Broker Backend
    ("apps_script_broker/Code.gs", "Google Apps Script Master Broker (Backend, Sheets, Drive, 70+ customers)"),
    ("apps_script_broker/appsscript.json", "Apps Script Manifest"),

    # 2. Client PowerShell Engine & Uninstallers
    ("shell_client/backup_agent.ps1", "Module 1: Pure PowerShell Database Backup Engine"),
    ("shell_client/performance_query.ps1", "Module 3: Database Performance Query & Reindexing Engine"),
    ("shell_client/storage_monitor.ps1", "Module 2: Server Storage Monitor & Cleanup Engine"),
    ("shell_client/install_agent.ps1", "Windows Task Scheduler Installer & Environment Provisioning"),
    ("shell_client/run_automation.ps1", "Master Multi-Task Orchestrator"),
    ("shell_client/uninstall_agent.ps1", "Pure PowerShell Agent Clean Uninstaller & Credential Shredder"),
    ("Uninstall.bat", "Enterprise 1-Click Self-Elevating Windows Application Uninstaller"),

    # 3. Cryptography & Security
    ("crypto_stream.py", "Core AES-256-GCM + RSA-OAEP Hybrid Streaming Crypto Engine"),
    ("admin/sign_bundle.py", "Ed25519 Configuration Signing & Verification Library"),
    ("audit_build.py", "Zero-Trust Build & Package Allowlist Security Audit"),

    # 4. Admin Provisioning & Recovery
    ("../Admin_Installation_Package/1_Customer_Provisioning/setup_new_customer.py", "Single Customer Setup Wizard"),
    ("../Admin_Installation_Package/1_Customer_Provisioning/batch_setup_customers.py", "Batch Customer Provisioning Wizard (70+ customers)"),
    ("../Admin_Installation_Package/2_Disaster_Recovery/decrypt_backup.py", "Disaster Recovery CLI Decryptor"),
    ("../Admin_Installation_Package/2_Disaster_Recovery/decrypt_backup.ps1", "Disaster Recovery Pure PowerShell Decryptor"),

    # 5. Architecture & Operational Docs
    ("../Admin_Installation_Package/4_Documentation/ADMIN_MASTER_OPERATIONS_MANUAL.md", "Admin Operations Manual"),
    ("../Admin_Installation_Package/4_Documentation/ARCHITECTURE_REFERENCE.md", "Architecture & Telemetry Specifications"),
    ("CLIENT_INSTALLATION_GUIDE.md", "Client Server Installation & Deployment Guide"),
]

PROMPT_HEADER = """# 🛡️ Enterprise Database Cloud Backup & Maintenance Suite
## Comprehensive Fail-Proof & Adversarial Security Audit Dossier

> **INSTRUCTIONS FOR CLAUDE (Senior Principal Distributed Systems & Cybersecurity Architect)**:
> You are conducting a rigorous, zero-mercy security, resilience, and reliability review of this production enterprise system.
> The system automates SQL Server backups, server disk cleanup, and index/performance maintenance across 70+ client servers, storing encrypted backups in Google Drive and telemetry in Google Sheets via a Google Apps Script broker.
>
> **YOUR MISSION**:
> Find any condition under which this system can FAIL, HANG, LEAK SECRETS, CORRUPT DATA, OR LOSE RECOVERY CAPABILITY.
>
> Focus specifically on:
> 1. **Zero-Trust Cryptographic Soundness**:
>    - Can a rogue/compromised customer server decrypt another customer's backups or historical backups?
>    - Are RSA-OAEP and AES-256-GCM authenticated context bindings tamper-proof against ciphertext transplantation?
>    - Is key escrow safe? Are private keys 100% prevented from leaking to clients?
> 2. **PowerShell & SQL Server Failure Modes**:
>    - SQL timeout handling: What happens if `DBCC CHECKDB` or `DBCC DBREINDEX` takes 6 hours? Does the script crash, hang, or leave indexes half-rebuilt?
>    - Deadlocks and blocking: Does `DBCC DBREINDEX ('?', ' ', 80)` block production transactions during business hours?
>    - Disk full during pre-maintenance safety backup: Does it abort gracefully without destroying remaining storage?
>    - Timezone discrepancies: Does `performance_query.ps1` handle edge cases (DST transitions, UTC offsets)?
> 3. **Google Apps Script & Serverless Scalability (70+ Customers)**:
>    - Google Apps Script 6-minute execution quota: Can chunked uploads or concurrent requests from 70 servers cause execution lockups or timeouts?
>    - Concurrency and lock contention: How does `LockService.getScriptLock()` behave when 10 servers post telemetry at 03:30 AM simultaneously?
>    - Google Sheet limits (10 million cells): Is appending rows sustainable, and are tab operations resilient?
> 4. **Windows Task Scheduler & System Automation**:
>    - Re-entrancy: What happens if a previous backup job is still running when the next scheduled task triggers?
>    - Execution policy bypass and path spaces: Are quotes, argument delimiters, and permissions fail-proof across Windows Server 2012R2 to 2025?
> 5. **Disaster Recovery Completeness**:
>    - If the client server burns to the ground, can an administrator restore the exact database using only the Drive archive and offline private key?

---

"""

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    zip_path = os.path.join(OUTPUT_DIR, "claude_failproof_audit_pack.zip")
    dossier_path = os.path.join(OUTPUT_DIR, "CLAUDE_FAILPROOF_AUDIT_DOSSIER.md")

    print("[*] Generating claude_failproof_audit_pack.zip...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path, desc in AUDIT_FILES:
            full_path = os.path.abspath(os.path.join(BASE_DIR, rel_path))
            if os.path.exists(full_path):
                arcname = os.path.basename(full_path)
                # Group by category in zip
                if "shell_client" in rel_path:
                    arcname = f"shell_client/{arcname}"
                elif "apps_script" in rel_path:
                    arcname = f"apps_script_broker/{arcname}"
                elif "Customer_Provisioning" in rel_path:
                    arcname = f"admin_provisioning/{arcname}"
                elif "Disaster_Recovery" in rel_path:
                    arcname = f"admin_recovery/{arcname}"
                elif "Documentation" in rel_path:
                    arcname = f"docs/{arcname}"
                zf.write(full_path, arcname)
                print(f"  + Added to zip: {arcname} ({os.path.getsize(full_path):,} bytes)")
            else:
                print(f"  [X] Not found: {full_path}")

    print(f"\n[OK] ZIP generated: {zip_path} ({os.path.getsize(zip_path):,} bytes)")

    print("\n[*] Generating CLAUDE_FAILPROOF_AUDIT_DOSSIER.md...")
    with open(dossier_path, "w", encoding="utf-8") as out:
        out.write(PROMPT_HEADER)
        out.write("## 📦 Index of Included Audit Files\n\n")
        for rel_path, desc in AUDIT_FILES:
            out.write(f"- **`{os.path.basename(rel_path)}`**: {desc}\n")
        out.write("\n---\n\n")

        for rel_path, desc in AUDIT_FILES:
            full_path = os.path.abspath(os.path.join(BASE_DIR, rel_path))
            if os.path.exists(full_path):
                ext = os.path.splitext(full_path)[1].lower().replace(".", "")
                lang_map = {"gs": "javascript", "ps1": "powershell", "py": "python", "json": "json", "md": "markdown"}
                lang = lang_map.get(ext, "")

                out.write(f"## 📄 File: `{os.path.basename(full_path)}`\n")
                out.write(f"> **Description**: {desc}  \n")
                out.write(f"> **Path**: `{rel_path}`  \n\n")
                out.write(f"```{lang}\n")
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    out.write(f.read())
                out.write("\n```\n\n---\n\n")

    print(f"[OK] Dossier generated: {dossier_path} ({os.path.getsize(dossier_path):,} bytes)")

if __name__ == "__main__":
    main()
