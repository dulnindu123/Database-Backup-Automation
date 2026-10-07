"""
Setup New Customer Script (Admin Provisioning Suite v4.2.0)
=============================================================================
Automates generation of customer RSA keys, creates the secure signed bundle.json,
and prepares a final deployment package folder containing everything the customer needs.

Key capabilities:
1. Generates 4096-bit RSA primary and escrow keypairs.
2. Generates random enrollment codes for zero-typing setup.
3. Cryptographically signs bundle.json with Admin Ed25519 signing key.
4. Segregates customer private keys to offline _keys folder.
"""
import os
import sys
import time
import json
import base64
import getpass
import hashlib
import re
import secrets
import shutil

# Resilient imports (standalone inside folder or within repository)
try:
    from sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError, in_sync_folder
except ImportError:
    try:
        from admin.sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError, in_sync_folder
    except ImportError:
        sys.path.insert(0, os.path.dirname(__file__))
        from sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError, in_sync_folder

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError as e:
    print(f"Error importing dependencies. Ensure you run 'Setup_Admin_Environment.bat' or 'pip install -r requirements.txt': {e}")
    sys.exit(1)

SLUG_RE = re.compile(r"^[a-z0-9]{2,24}$")
URL_RE = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]{20,200}/exec$")


def generate_rsa_keypair(passphrase: str) -> tuple:
    """Generates a 4096-bit RSA key and returns (private_pem_bytes, public_pem_bytes)"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    priv = key.private_bytes(
        serialization.Encoding.PEM, 
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode())
    )
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, 
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv, pub


def main():
    print("=" * 60)
    print("   EASY CUSTOMER SETUP WIZARD (Admin Zero-Trust Provisioning)")
    print("=" * 60)
    print("This tool generates secure keys and a signed bundle for a new customer.\n")

    # 1. Customer Details
    while True:
        slug = input("Enter customer short name (slug) [e.g. acme, 2 to 24 lowercase letters/numbers]: ").strip().lower()
        if SLUG_RE.match(slug):
            break
        print("Invalid slug. Use only lowercase letters and numbers (2-24 chars).")

    while True:
        url = input("Enter the Google Apps Script Broker URL (must start with https://script.google.com/...): ").strip()
        if URL_RE.match(url):
            break
        print("Invalid URL format. Please paste the exact Web App URL.")

    print("\n[RSA Keys Generation]")
    print(f"We will generate two distinct 4096-bit RSA keys for '{slug}'.")
    while True:
        cust_pw = getpass.getpass("Choose a strong passphrase for the NEW customer's private keys: ")
        if len(cust_pw) < 14:
            print("Passphrase must be at least 14 characters.")
            continue
        cust_pw2 = getpass.getpass("Repeat passphrase: ")
        if cust_pw == cust_pw2:
            break
        print("Passphrases do not match. Try again.")

    print("\nGenerating Primary and Escrow keys... (this may take a few seconds)")
    primary_priv, primary_pub = generate_rsa_keypair(cust_pw)
    escrow_priv, escrow_pub = generate_rsa_keypair(cust_pw)
    print("Keys generated successfully.")

    print("\n[Bundle Signing]")
    default_admin_key = "admin_ed25519.pem"
    try:
        if in_sync_folder(os.path.abspath(default_admin_key)):
            safe_path = "C:\\admin_ed25519.pem"
            if not in_sync_folder(safe_path):
                default_admin_key = safe_path
    except Exception:
        pass

    admin_key_path = input(f"Enter path to your Admin Ed25519 Private Key [default: {default_admin_key}]: ").strip()
    if not admin_key_path:
        admin_key_path = default_admin_key

    if not os.path.exists(admin_key_path):
        print(f"\nAdmin key '{admin_key_path}' not found.")
        ans = input("Would you like to initialize a new Admin Signing Key now? (y/N): ").strip().lower()
        if ans == 'y':
            while True:
                admin_pw = getpass.getpass("Choose a strong passphrase for the NEW Admin Key (14+ chars): ")
                if len(admin_pw) < 14:
                    print("Passphrase must be at least 14 characters.")
                    continue
                admin_pw2 = getpass.getpass("Repeat passphrase: ")
                if admin_pw == admin_pw2:
                    break
                print("Passphrases do not match. Try again.")
            try:
                pub_pem_str = init_key(admin_key_path, admin_pw)
                print(f"Admin key created at '{admin_key_path}'.")
            except BundleError as e:
                print(f"Failed to create admin key: {e}")
                sys.exit(1)
        else:
            print("Cannot proceed without an admin signing key.")
            sys.exit(1)

    while True:
        admin_pw = getpass.getpass(f"Enter passphrase for the Admin Signing Key '{admin_key_path}': ")
        try:
            admin_priv_key = load_private(admin_key_path, admin_pw)
            break
        except Exception as e:
            print(f"Failed to load admin key (wrong passphrase?): {e}")

    # Generate a random enrollment code for zero-typing
    enroll_code = secrets.token_urlsafe(16)

    try:
        bundle_dict = build_bundle(slug, url, primary_pub, escrow_pub, enroll_code=enroll_code)
        bundle_b64, signature_b64 = sign_bundle(admin_priv_key, bundle_dict)
    except BundleError as e:
        print(f"\nFailed to build or sign bundle: {e}")
        sys.exit(1)

    # Output paths (store in customers folder inside admin package root)
    admin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir_pkg = os.path.join(admin_root, "customers", f"{slug}_package")
    out_dir_keys = os.path.join(admin_root, "customers", f"{slug}_keys")
    os.makedirs(out_dir_pkg, exist_ok=True)
    os.makedirs(out_dir_keys, exist_ok=True)

    # Write private keys offline
    with open(os.path.join(out_dir_keys, "backup_private.pem"), "wb") as f:
        f.write(primary_priv)
    with open(os.path.join(out_dir_keys, "escrow_private.pem"), "wb") as f:
        f.write(escrow_priv)
        
    # Write public keys to package
    with open(os.path.join(out_dir_pkg, "backup_public.pem"), "wb") as f:
        f.write(primary_pub)
    with open(os.path.join(out_dir_pkg, "escrow_public.pem"), "wb") as f:
        f.write(escrow_pub)

    # Write bundle.json
    bundle_file_data = {
        "BUNDLE_B64": bundle_b64,
        "SIGNATURE_B64": signature_b64
    }
    with open(os.path.join(out_dir_pkg, "bundle.json"), "w", encoding="utf-8") as f:
        json.dump(bundle_file_data, f, indent=2)

    print("\n" + "="*60)
    print(f" SUCCESS! Package for '{slug}' prepared.")
    print("="*60)
    print(f"\n👉 NEXT STEP (Google Sheet Config tab):")
    print("Paste this as one row starting at column A (A=ENROLL_CODE, B=code, C=slug):")
    print(f"ENROLL_CODE\t{enroll_code}\t{slug}")
    print(f"\nSECURE OFFLINE KEYS saved to:\n  {out_dir_keys}\n  (DO NOT send these to the customer. Keep them safely offline!)")
    print(f"\nCUSTOMER PACKAGE saved to:\n  {out_dir_pkg}")
    
    # Check if Client_Installation_Package is available to auto-copy
    candidate_client_pkg = [
        os.path.abspath(os.path.join(admin_root, "..", "Client_Installation_Package")),
        os.path.abspath(os.path.join(admin_root, "..", "BackupAutomation", "Client_Installation_Package"))
    ]
    client_pkg_dir = next((p for p in candidate_client_pkg if os.path.exists(p)), None)

    if client_pkg_dir:
        installer_src = os.path.join(client_pkg_dir, "Setup_DatabaseBackup.exe")
        appfiles_src = os.path.join(client_pkg_dir, "AppFiles")
        shell_src = os.path.join(client_pkg_dir, "shell_client")

        if os.path.exists(installer_src):
            shutil.copy2(installer_src, os.path.join(out_dir_pkg, "Setup_DatabaseBackup.exe"))
        if os.path.exists(appfiles_src):
            shutil.copytree(appfiles_src, os.path.join(out_dir_pkg, "AppFiles"), dirs_exist_ok=True)
        if os.path.exists(shell_src):
            shutil.copytree(shell_src, os.path.join(out_dir_pkg, "shell_client"), dirs_exist_ok=True)
            
        for root_file in ["Uninstall.bat", "Update_App.bat", "CLIENT_INSTALLATION_GUIDE.md", "READ_ME_FIRST.txt"]:
            src_rf = os.path.join(client_pkg_dir, root_file)
            if os.path.exists(src_rf):
                shutil.copy2(src_rf, os.path.join(out_dir_pkg, root_file))
            
        print(f"\n✅ Automatically mirrored client installer, shell client, uninstaller, and docs to {out_dir_pkg}")
        print(f"👉 Simply zip the folder '{slug}_package' and provide it to customer '{slug}'.")
    else:
        print("\nNote: Copy Setup_DatabaseBackup.exe or shell_client into the package folder before delivery.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(0)
