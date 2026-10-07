"""
Batch Customer Setup (Admin Provisioning Suite v4.2.0)
=============================================================================
Provisions many customers in one run:
  - Reads slugs from customer_slugs.txt (one per line; 'slug' or 'slug,Display Name')
  - Asks for Broker URL ONCE and Admin signing key passphrase ONCE
  - Generates 4096-bit RSA keys for each customer
  - Cryptographically signs bundle.json for each customer
  - Prepares self-contained customer packages (with Setup_DatabaseBackup.exe & shell_client)
  - Exports enroll_codes.csv and enroll_codes_for_sheet.tsv ready to paste into Sheet Config
"""
import os
import sys
import json
import getpass
import secrets
import shutil
import csv

# Resilient imports
try:
    from setup_new_customer import SLUG_RE, URL_RE, generate_rsa_keypair
    from sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from setup_new_customer import SLUG_RE, URL_RE, generate_rsa_keypair
    from sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError

ADMIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SLUG_FILE = os.path.join(os.path.dirname(__file__), "customer_slugs.txt")


def read_slugs():
    items = []
    with open(SLUG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",", 1)]
            slug = parts[0].lower()
            name = parts[1] if len(parts) > 1 else slug
            items.append((slug, name))
    return items


def ask_pw(label):
    while True:
        a = getpass.getpass(f"{label} (14+ chars): ")
        if len(a) < 14:
            print("  Too short (minimum 14 characters required).")
            continue
        if a == getpass.getpass("  Repeat: "):
            return a
        print("  Passphrases do not match. Try again.")


def main():
    if not os.path.exists(SLUG_FILE):
        print(f"Missing {SLUG_FILE}")
        sys.exit(1)
        
    items = read_slugs()
    bad = [s for s, _ in items if not SLUG_RE.match(s)]
    dup = {s for s, _ in items if [x for x, _ in items].count(s) > 1}
    if bad or dup:
        print("Fix slug list first. Invalid:", bad, "Duplicates:", sorted(dup))
        sys.exit(1)
        
    print("=" * 65)
    print("  ENTERPRISE BATCH PROVISIONING WIZARD (Admin Only)")
    print("=" * 65)
    print(f"Found {len(items)} customers in queue to provision.\n")

    import argparse
    parser = argparse.ArgumentParser(description="Batch Customer Setup")
    parser.add_argument("--url", help="Apps Script Broker URL")
    parser.add_argument("--key", help="Admin Ed25519 private key path")
    parser.add_argument("--passphrase", help="Shared customer recovery keys passphrase (14+ chars)")
    args, _ = parser.parse_known_args()

    url = args.url
    while not url or not URL_RE.match(url):
        url = input("Apps Script Broker URL (https://script.google.com/macros/s/.../exec): ").strip()
        if not URL_RE.match(url):
            print("Invalid URL.")

    default_key = os.path.join(ADMIN_ROOT, "keys", "admin_ed25519_private.pem")
    if not os.path.exists(default_key):
        default_key = "C:\\admin_ed25519.pem"
        
    key_path = args.key or default_key
    if not args.key:
        key_path = input(f"Admin Ed25519 key path [{default_key}]: ").strip() or default_key
        
    if not os.path.exists(key_path):
        if input("Not found. Create new admin key? (y/N): ").strip().lower() != "y":
            sys.exit(1)
        init_key(key_path, ask_pw("New Admin key passphrase"))
        
    while True:
        try:
            try:
                admin_priv = load_private(key_path, "")
            except Exception:
                admin_priv = load_private(key_path, getpass.getpass("Admin key passphrase: "))
            break
        except Exception as e:
            print("Failed to load:", e)

    shared_pw = args.passphrase
    if not shared_pw:
        if input("\nUse ONE shared passphrase for all customers' private keys? (y/N): ").strip().lower() == "y":
            while True:
                p = getpass.getpass("Shared passphrase (14+ chars): ")
                if p != getpass.getpass("  Repeat: "):
                    print("  Do not match.")
                    continue
                if len(p) < 14:
                    print(f"  WARNING: only {len(p)} chars (14+ recommended).")
                    if input("  Use it anyway? (y/N): ").strip().lower() != "y":
                        continue
                shared_pw = p
                break

    cust_dir = os.path.join(ADMIN_ROOT, "customers")
    os.makedirs(cust_dir, exist_ok=True)
    
    # Locate Client_Installation_Package source if available
    candidate_client_pkg = [
        os.path.abspath(os.path.join(ADMIN_ROOT, "..", "Client_Installation_Package")),
        os.path.abspath(os.path.join(ADMIN_ROOT, "..", "BackupAutomation", "Client_Installation_Package"))
    ]
    client_pkg = next((p for p in candidate_client_pkg if os.path.exists(p)), None)
    
    installer = os.path.join(client_pkg, "Setup_DatabaseBackup.exe") if client_pkg and os.path.exists(os.path.join(client_pkg, "Setup_DatabaseBackup.exe")) else None
    appfiles = os.path.join(client_pkg, "AppFiles") if client_pkg and os.path.exists(os.path.join(client_pkg, "AppFiles")) else None
    shell_src = os.path.join(client_pkg, "shell_client") if client_pkg and os.path.exists(os.path.join(client_pkg, "shell_client")) else None

    csv_path = os.path.join(cust_dir, "enroll_codes.csv")
    tsv_path = os.path.join(cust_dir, "enroll_codes_for_sheet.tsv")
    new_csv = not os.path.exists(csv_path)
    done = 0

    print("\nStarting batch key generation and bundle signing...")
    for i, (slug, name) in enumerate(items, 1):
        pkg = os.path.join(cust_dir, f"{slug}_package")
        keys = os.path.join(cust_dir, f"{slug}_keys")
        if os.path.exists(os.path.join(pkg, "bundle.json")):
            print(f"[{i}/{len(items)}] {name} ({slug}): already provisioned, skipping.")
            continue
            
        print(f"[{i}/{len(items)}] Provisioning: {name} ({slug})...")
        pw = shared_pw or ask_pw(f"Passphrase for {slug}'s private keys")
        p_priv, p_pub = generate_rsa_keypair(pw)
        e_priv, e_pub = generate_rsa_keypair(pw)
        code = secrets.token_urlsafe(16)
        
        try:
            b64, sig = sign_bundle(admin_priv, build_bundle(slug, url, p_pub, e_pub, enroll_code=code))
        except BundleError as e:
            print("  FAILED:", e)
            continue
            
        os.makedirs(pkg, exist_ok=True)
        os.makedirs(keys, exist_ok=True)
        
        for path, data in ((os.path.join(keys, "backup_private.pem"), p_priv),
                           (os.path.join(keys, "escrow_private.pem"), e_priv),
                           (os.path.join(pkg, "backup_public.pem"), p_pub),
                           (os.path.join(pkg, "escrow_public.pem"), e_pub)):
            with open(path, "wb") as f:
                f.write(data)
                
        with open(os.path.join(pkg, "bundle.json"), "w", encoding="utf-8") as f:
            json.dump({"BUNDLE_B64": b64, "SIGNATURE_B64": sig}, f, indent=2)
            
        if installer:
            shutil.copy2(installer, os.path.join(pkg, "Setup_DatabaseBackup.exe"))
            if appfiles:
                shutil.copytree(appfiles, os.path.join(pkg, "AppFiles"), dirs_exist_ok=True)
        if shell_src:
            shutil.copytree(shell_src, os.path.join(pkg, "shell_client"), dirs_exist_ok=True)
            
        if client_pkg:
            for root_file in ["Uninstall.bat", "Update_App.bat", "CLIENT_INSTALLATION_GUIDE.md", "READ_ME_FIRST.txt"]:
                src_rf = os.path.join(client_pkg, root_file)
                if os.path.exists(src_rf):
                    shutil.copy2(src_rf, os.path.join(pkg, root_file))
            
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_csv:
                w.writerow(["slug", "customer_name", "ENROLL_CODE"])
                new_csv = False
            w.writerow([slug, name, code])
            
        with open(tsv_path, "a", encoding="utf-8") as f:
            f.write(f"ENROLL_CODE\t{code}\t{slug}\n")
            
        done += 1
        print(f"  -> Package created: {pkg}")

    print("\n" + "=" * 65)
    print(f" Batch Provisioning Complete! {done} customer packages created.")
    print("=" * 65)
    print(f"1. Sheet Config rows saved to: {tsv_path}")
    print("   Copy and paste these rows into your Google Sheet 'Config' tab.")
    print(f"2. Customer private keys saved to: {cust_dir}")
    print("   ⚠️ KEEP all '*_keys' folders strictly offline!")
    print(f"3. Customer packages saved in: {cust_dir}")
    print("   Deliver each '<slug>_package' to its respective customer.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBatch setup cancelled.")
