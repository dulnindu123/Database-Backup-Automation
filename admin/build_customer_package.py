"""
Admin One-Command Customer Package Builder for Database Cloud Backup
=============================================================================
Automates the complete provisioning and packaging workflow for a new customer PC.

What it does in ONE step:
1. Auto-fetches the live Cloud Run Upload Broker URL via `gcloud`.
2. Generates a cryptographically strong, unique machine token (<pc_id>.<secret>).
3. Automatically updates Google Cloud Secret Manager (pc-tokens) with the SHA-256 hash.
4. Generates a customized, standalone Customer Installation Package:
   - Broker URL is pre-configured and locked.
   - Google Drive Folder ID & Google Sheet ID are left BLANK for the customer to input.
   - Includes raw_token.txt which the installer automatically seals into Windows DPAPI
     and cryptographically shreds upon installation on the customer PC.
5. Packages everything into a ready-to-deliver ZIP file for the customer.

Usage:
  python admin/build_customer_package.py --customer "AcmeCorp" [--pc-id "pc-acme-01"]
"""

import os
import sys
import json
import shutil
import secrets
import hashlib
import zipfile
import argparse
import subprocess
from datetime import datetime


def run_cmd(cmd_list, capture=True, timeout=20):
    """Executes a system command with error capture."""
    try:
        res = subprocess.run(
            cmd_list,
            capture_output=capture,
            text=True,
            timeout=timeout,
            shell=sys.platform.startswith("win")
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def get_gcloud_broker_url(region="us-central1"):
    """Auto-detects the live Cloud Run upload-broker URL from GCP."""
    cmd = ["gcloud", "run", "services", "describe", "upload-broker", f"--region={region}", "--format=value(status.url)"]
    rc, stdout, stderr = run_cmd(cmd)
    if rc == 0 and stdout.startswith("https://"):
        return stdout.strip()
    return ""


def get_gcp_project_id():
    """Gets current configured GCP project."""
    rc, stdout, _ = run_cmd(["gcloud", "config", "get-value", "project"])
    return stdout if rc == 0 and stdout else ""


def update_secret_manager(pc_id, token_hash, project_id=None):
    """Updates pc-tokens secret in GCP Secret Manager with the new PC ID hash."""
    print(f"[*] Querying GCP Secret Manager for 'pc-tokens'...")
    access_cmd = ["gcloud", "secrets", "versions", "access", "latest", "--secret=pc-tokens"]
    if project_id:
        access_cmd.append(f"--project={project_id}")
    
    rc, stdout, stderr = run_cmd(access_cmd)
    tokens_data = {}
    if rc == 0 and stdout:
        try:
            tokens_data = json.loads(stdout)
        except Exception:
            tokens_data = {}
    else:
        print(f"    [!] Could not read existing secret versions: {stderr}")
        print("    [!] Attempting to initialize fresh dictionary...")

    tokens_data[pc_id] = token_hash
    updated_json = json.dumps(tokens_data, indent=2)

    # Push updated version
    print(f"[*] Registering {pc_id} in GCP Secret Manager (pc-tokens)...")
    temp_json_path = os.path.join(os.environ.get("TEMP", "."), f"pc_tokens_{pc_id}.json")
    try:
        with open(temp_json_path, "w", encoding="utf-8") as f:
            f.write(updated_json)

        add_cmd = ["gcloud", "secrets", "versions", "add", "pc-tokens", f"--data-file={temp_json_path}"]
        if project_id:
            add_cmd.append(f"--project={project_id}")

        rc, stdout, stderr = run_cmd(add_cmd)
        if rc == 0:
            print(f"    [OK] Successfully added new secret version for {pc_id}")
            return True
        else:
            print(f"    [!] Failed to update Secret Manager via gcloud: {stderr}")
            return False
    finally:
        if os.path.exists(temp_json_path):
            try:
                os.remove(temp_json_path)
            except Exception:
                pass


def remove_readonly(func, path, excinfo):
    """Clears read-only attribute on Windows and retries deletion."""
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def build_package(customer_name, pc_id, broker_url, skip_gcp=False, region="us-central1"):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dist_packages_dir = os.path.join(base_dir, "dist", "packages")
    os.makedirs(dist_packages_dir, exist_ok=True)

    # Master template source
    source_template = os.path.join(base_dir, "..", "Client_Installation_Package")
    if not os.path.exists(source_template):
        source_template = os.path.join(base_dir, "Client_Installation_Package")
    
    if not os.path.exists(source_template):
        print(f"[ERROR] Master template folder not found at: {source_template}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  ENTERPRISE DATABASE CLOUD BACKUP - CUSTOMER PACKAGE BUILDER")
    print(f"  Customer: {customer_name} | PC ID: {pc_id}")
    print("=" * 70)

    # 1. Resolve Broker URL
    if not broker_url:
        print("[*] Auto-fetching live Cloud Run broker URL from GCP...")
        broker_url = get_gcloud_broker_url(region=region)
        if broker_url:
            print(f"    [OK] Detected Broker URL: {broker_url}")
        else:
            print("    [!] Could not auto-fetch Cloud Run URL via gcloud CLI.")
            broker_url = input("    Please enter your Cloud Run Broker URL manually: ").strip()

    if not broker_url:
        print("[ERROR] Broker URL is required to build customer package.")
        sys.exit(1)

    # 2. Generate Cryptographic Machine Token
    secret = secrets.token_hex(24)
    raw_token = f"{pc_id}.{secret}"
    token_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    print(f"[*] Generated machine authentication token for {pc_id}")

    # 3. Register in GCP Secret Manager
    if not skip_gcp:
        project_id = get_gcp_project_id()
        success = update_secret_manager(pc_id, token_hash, project_id)
        if not success:
            print("\n[WARNING] Could not auto-update GCP Secret Manager via gcloud.")
            print("Please manually append this JSON entry into your Secret Manager 'pc-tokens':")
            print(json.dumps({pc_id: token_hash}, indent=2))
            print()
    else:
        print("[*] Skipping GCP Secret Manager registration (--skip-gcp flag enabled).")
        print("    Add this hash to Secret Manager manually:")
        print(f'    "{pc_id}": "{token_hash}"')

    # 4. Clone template to dedicated customer folder
    clean_cust_name = "".join(c for c in customer_name if c.isalnum() or c in ("-", "_")).strip()
    target_pkg_name = f"Client_Installation_Package_{clean_cust_name}"
    target_pkg_dir = os.path.join(dist_packages_dir, target_pkg_name)

    if os.path.exists(target_pkg_dir):
        print(f"[*] Removing previous build at: {target_pkg_dir}")
        shutil.rmtree(target_pkg_dir, onexc=remove_readonly)

    print(f"[*] Cloning master package into: {target_pkg_dir}...")
    shutil.copytree(source_template, target_pkg_dir)

    # 5. Pre-configure config.json (Broker URL set, Drive/Sheet IDs left EMPTY for customer)
    app_files_config = os.path.join(target_pkg_dir, "AppFiles", "config.json")
    if os.path.exists(app_files_config):
        try:
            with open(app_files_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        
        cfg["BROKER_URL"] = broker_url
        cfg["TELEMETRY_BROKER_URL"] = broker_url
        # Explicitly ensure Drive and Sheet IDs are empty for the customer to input
        cfg["GOOGLE_DRIVE_FOLDER_ID"] = ""
        cfg["GOOGLE_SHEET_ID"] = ""

        with open(app_files_config, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        print("    [OK] Injected live Broker URL into AppFiles/config.json")
        print("    [OK] Set GOOGLE_DRIVE_FOLDER_ID and GOOGLE_SHEET_ID to empty (Customer will enter)")

    # 6. Write raw_token.txt in package root
    raw_token_path = os.path.join(target_pkg_dir, "raw_token.txt")
    with open(raw_token_path, "w", encoding="utf-8") as f:
        f.write(raw_token.strip() + "\n")
    print("    [OK] Injected raw_token.txt for automated Windows DPAPI zero-touch import")

    # 7. Create ZIP archive
    zip_filename = f"{target_pkg_name}.zip"
    zip_filepath = os.path.join(dist_packages_dir, zip_filename)
    print(f"[*] Compressing package into: {zip_filepath}...")
    
    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(target_pkg_dir):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, target_pkg_dir)
                zf.write(abs_path, rel_path)

    print("\n" + "=" * 70)
    print(f"[SUCCESS] CUSTOMER PACKAGE READY FOR RELEASE: {customer_name}")
    print("=" * 70)
    print(f"Output Folder : {target_pkg_dir}")
    print(f"Distribution  : {zip_filepath}")
    print(f"Broker URL    : {broker_url}")
    print(f"PC Identifier : {pc_id}")
    print("-" * 70)
    print("CUSTOMER EXPERIENCE (ZERO TECHNICAL EFFORT):")
    print(f"1. Send '{zip_filename}' to the customer.")
    print("2. Customer unzips and runs 'Setup_DatabaseBackup.exe' (or '1_Quick_Install.bat').")
    print("   -> Broker URL is pre-verified and token is automatically imported into Windows DPAPI.")
    print("   -> raw_token.txt is automatically shredded and wiped.")
    print("3. Customer opens the application and enters their own Google Drive Folder ID & Sheet ID.")
    print("   -> Clicks 'Save Settings' and is fully operational.")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="One-Command Customer Package Builder for Database Cloud Backup.")
    parser.add_argument("--customer", required=True, help="Customer name or organization (e.g. AcmeCorp)")
    parser.add_argument("--pc-id", help="Unique identifier for the PC (defaults to pc-<customer>-01)")
    parser.add_argument("--broker-url", help="Cloud Run broker URL (auto-fetched via gcloud if omitted)")
    parser.add_argument("--region", default="us-central1", help="GCP Cloud Run region (default: us-central1)")
    parser.add_argument("--skip-gcp", action="store_true", help="Skip updating Secret Manager via gcloud CLI")
    args = parser.parse_args()

    clean_cust = "".join(c for c in args.customer.lower() if c.isalnum() or c in ("-", "_")).strip("-").strip("_")
    pc_id = args.pc_id.strip() if args.pc_id else f"pc-{clean_cust}-01"

    build_package(
        customer_name=args.customer,
        pc_id=pc_id,
        broker_url=args.broker_url,
        skip_gcp=args.skip_gcp,
        region=args.region
    )


if __name__ == "__main__":
    main()
