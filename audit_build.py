"""
Zero-Trust Build & Package Allowlist Security Audit (v4.2.0)
=============================================================================
Enforces strict verification on Client_Installation_Package and dist/:
1. Explicit Allowlist: Fails build if any unexpected file is present.
2. Zero Stray Configs: Fails build if any unallowed *.txt file is present.
3. Master Template Integrity: Fails build if master config.json has non-empty
   BROKER_URL, GOOGLE_DRIVE_FOLDER_ID, or GOOGLE_SHEET_ID.
4. Secret Guard: Fails build if any private key, OAuth secret, or token is detected.
"""

import os
import sys
import json

ALLOWED_PACKAGE_ROOT_FILES = {
    "Setup_DatabaseBackup.exe",
    "Update_App.bat",
    "Uninstall.bat",
    "READ_ME_FIRST.txt",
    "README.md",
    "CLIENT_INSTALLATION_GUIDE.md",
    "CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx",
    "app_icon.ico",
    "app_icon.png",
    "sha256_manifest.json",
    "build_info.json",
}

ALLOWED_PACKAGE_ROOT_DIRS = {
    "AppFiles",
    "shell_client",
}

ALLOWED_APPFILES_FILES = {
    "DatabaseBackupApp.exe",
    "Uninstall.bat",
    "backup_public.pem",
    "escrow_public.pem",
    "config.json",
    "build_info.json",
    "sha256_manifest.json",
}

ALLOWED_APPFILES_DIRS = {
    "_internal",
}

FORBIDDEN_SECRET_FILES = [
    "client_secret.json",
    "credentials.json",
    "token.json",
    "broker_token.dat",
    "token.dpapi",
    "raw_token.txt",
    "broker_url.txt",
    "drive_folder.txt",
    "sheet_id.txt",
    "backup_log.txt",
]

FORBIDDEN_ADMIN_FILES = [
    "decrypt_backup.py",
    "decrypt_backup.ps1",
    "decrypt_gui.py",
    "setup_new_customer.py",
    "batch_setup_customers.py",
    "customer_slugs.txt",
    "generate_keys.py",
    "sign_bundle.py",
    "admin_ed25519_private.pem",
    "backup_private.pem",
    "escrow_private.pem",
    "pull_backup.py",
    "Code.gs",
]


def audit_master_package(pkg_dir):
    """Audits Client_Installation_Package against explicit allowlists and empty template fields."""
    errors = []
    if not os.path.exists(pkg_dir):
        return [f"Package directory not found: {pkg_dir}"]

    # 1. Inspect Root Entries
    for entry in os.listdir(pkg_dir):
        full_p = os.path.join(pkg_dir, entry)
        if os.path.isdir(full_p):
            if entry not in ALLOWED_PACKAGE_ROOT_DIRS:
                errors.append(f"Disallowed directory in package root: '{entry}' (Not on allowlist)")
        else:
            if entry not in ALLOWED_PACKAGE_ROOT_FILES:
                errors.append(f"Disallowed file in package root: '{entry}' (Not on allowlist)")

    # 2. Inspect AppFiles Entries
    app_files_dir = os.path.join(pkg_dir, "AppFiles")
    if not os.path.exists(app_files_dir):
        errors.append("AppFiles directory missing from package")
    else:
        for entry in os.listdir(app_files_dir):
            full_p = os.path.join(app_files_dir, entry)
            if os.path.isdir(full_p):
                if entry not in ALLOWED_APPFILES_DIRS:
                    errors.append(f"Disallowed directory in AppFiles: '{entry}' (Not on allowlist)")
            else:
                if entry not in ALLOWED_APPFILES_FILES:
                    errors.append(f"Disallowed file in AppFiles: '{entry}' (Not on allowlist)")

    # 3. Master config.json verification (BROKER_URL, Drive ID, Sheet ID must be EMPTY)
    cfg_path = os.path.join(app_files_dir, "config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as fp:
                cfg = json.load(fp)
            
            broker_url = cfg.get("BROKER_URL", "").strip()
            customer_slug = cfg.get("CUSTOMER_SLUG", "").strip()
            drive_id = cfg.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
            sheet_id = cfg.get("GOOGLE_SHEET_ID", "").strip()

            if broker_url != "":
                errors.append(f"Master config.json violation: BROKER_URL must be empty (Found: '{broker_url}')")
            if customer_slug != "":
                errors.append(f"Master config.json violation: CUSTOMER_SLUG must be empty (Found: '{customer_slug}')")
            if drive_id != "":
                errors.append(f"Master config.json violation: GOOGLE_DRIVE_FOLDER_ID must be empty (Found: '{drive_id}')")
            if sheet_id != "":
                errors.append(f"Master config.json violation: GOOGLE_SHEET_ID must be empty (Found: '{sheet_id}')")
        except Exception as e:
            errors.append(f"Failed to parse AppFiles/config.json: {e}")

    # 4. Check for forbidden admin tools and secrets across entire package
    for root, dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.lower() in [s.lower() for s in FORBIDDEN_SECRET_FILES]:
                errors.append(f"Forbidden secret file discovered in client package: '{os.path.join(root, f)}'")
            if f.lower() in [s.lower() for s in FORBIDDEN_ADMIN_FILES]:
                errors.append(f"Forbidden admin tool/file leaked into client package: '{os.path.join(root, f)}'")
            if f.endswith(".pem"):
                p = os.path.join(root, f)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                        if "PRIVATE KEY" in fp.read():
                            errors.append(f"Private encryption key leaked in client package: '{p}'")
                except Exception:
                    pass

    return errors


def audit_dist_secrets(dist_dir):
    """Scans dist/ directory to ensure 0 secret leaks or private keys."""
    errors = []
    if not os.path.exists(dist_dir):
        return []

    for root, dirs, files in os.walk(dist_dir):
        rel_root = os.path.relpath(root, dist_dir)
        is_internal = "_internal" in rel_root
        for f in files:
            # Check forbidden filenames
            if f.lower() in [s.lower() for s in FORBIDDEN_SECRET_FILES]:
                errors.append(f"Forbidden secret file discovered in dist: '{os.path.join(root, f)}'")
            # Check for stray .txt files outside _internal runtime
            elif not is_internal and f.endswith(".txt") and f != "READ_ME_FIRST.txt":
                errors.append(f"Unallowed stray .txt file in dist: '{os.path.join(root, f)}'")
            # Check for PEM private keys anywhere
            elif f.endswith(".pem"):
                p = os.path.join(root, f)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                        if "PRIVATE KEY" in content:
                            errors.append(f"Private encryption key leaked in dist: '{p}'")
                except Exception:
                    pass

    return errors


def main():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    pkg_dir = os.path.join(base_dir, "..", "Client_Installation_Package")
    if not os.path.exists(pkg_dir):
        pkg_dir = os.path.join(base_dir, "Client_Installation_Package")
    dist_dir = os.path.join(base_dir, "dist")

    print("=" * 70)
    print("  ZERO-TRUST BUILD & PACKAGE ALLOWLIST AUDIT")
    print("=" * 70)

    pkg_errors = audit_master_package(pkg_dir)
    dist_errors = audit_dist_secrets(dist_dir)

    all_errors = pkg_errors + dist_errors

    if all_errors:
        print("\n[CRITICAL FAILURE] Build Audit failed with violations:")
        for err in all_errors:
            print(f"  [X] {err}")
        print("\nBuild aborted to prevent leaking unverified or sensitive files.\n")
        sys.exit(1)
    else:
        print("\n[OK] Package Allowlist Audit: All files match strict explicit allowlist.")
        print("[OK] Master Config Audit: BROKER_URL, Drive ID, and Sheet ID are strictly empty.")
        print("[OK] Secret Guard Audit: 0 private keys or secret files detected.")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()
