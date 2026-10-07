"""
Setup New Customer Script

Automates generation of customer RSA keys, creates the secure bundle.json,
and prepares a final folder containing everything the customer needs.

It replaces the manual steps of:
1. Running generate_keys.py twice.
2. Running sign_bundle.py with long command line arguments.
"""
import os
import sys
import time
import json
import base64
import getpass
import hashlib
import re

# Insert parent directory into path so we can import admin.sign_bundle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from admin.sign_bundle import build_bundle, sign_bundle, load_private, init_key, BundleError
except ImportError as e:
    print(f"Error importing dependencies. Ensure you have installed 'cryptography': {e}")
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
    print("   EASY CUSTOMER SETUP WIZARD (Zero-Trust Provisioning)")
    print("=" * 60)
    print("This script will generate secure keys and a signed bundle for a new customer.\n")

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
    # Determine a safe default path for the admin key
    default_admin_key = "admin_ed25519.pem"
    try:
        from admin.sign_bundle import in_sync_folder
        if in_sync_folder(os.path.abspath(default_admin_key)):
            safe_path = "C:\\admin_ed25519.pem"
            if not in_sync_folder(safe_path):
                default_admin_key = safe_path
    except ImportError:
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
                print(f"Admin key created at '{admin_key_path}'. (The public key must be embedded in the installer in version.py!)")
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
    import secrets
    enroll_code = secrets.token_urlsafe(16)

    try:
        bundle_dict = build_bundle(slug, url, primary_pub, escrow_pub, enroll_code=enroll_code)
        bundle_b64, signature_b64 = sign_bundle(admin_priv_key, bundle_dict)
    except BundleError as e:
        print(f"\nFailed to build or sign bundle: {e}")
        sys.exit(1)

    # Output paths
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    out_dir_pkg = os.path.join(base_dir, "customers", f"{slug}_package")
    out_dir_keys = os.path.join(base_dir, "customers", f"{slug}_keys")
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
    print(f"\nSECURE OFFLINE KEYS saved to:\n  {out_dir_keys}\n  (DO NOT send these to the customer. Keep them safe.)\n")
    print(f"CUSTOMER PACKAGE saved to:\n  {out_dir_pkg}")
    print(f"\nCUSTOMER DEPLOYMENT:")
    
    # Auto-copy installer and AppFiles if they exist
    client_pkg_dir = os.path.abspath(os.path.join(base_dir, "..", "Client_Installation_Package"))
    dist_dir = os.path.join(base_dir, "dist")
    
    installer_src = os.path.join(client_pkg_dir, "Setup_DatabaseBackup.exe")
    if not os.path.exists(installer_src):
        installer_src = os.path.join(dist_dir, "Setup_DatabaseBackup.exe")
        
    appfiles_src = os.path.join(client_pkg_dir, "AppFiles")
    if not os.path.exists(appfiles_src):
        appfiles_src = os.path.join(dist_dir, "AppFiles")

    copied_installer = False
    if os.path.exists(installer_src):
        import shutil
        shutil.copy2(installer_src, os.path.join(out_dir_pkg, "Setup_DatabaseBackup.exe"))
        if os.path.exists(appfiles_src):
            shutil.copytree(appfiles_src, os.path.join(out_dir_pkg, "AppFiles"), dirs_exist_ok=True)
        copied_installer = True
        print(f"1. ✅ Automatically copied Setup_DatabaseBackup.exe and AppFiles into {out_dir_pkg}")
        print(f"2. Zip the '{slug}_package' folder and send it to the customer.")
        print(f"3. When they run the installer, it will zero-typing auto-configure everything!")
    else:
        print(f"1. Copy 'Setup_DatabaseBackup.exe' and the 'AppFiles' folder into {out_dir_pkg}")
        print("2. Zip the folder and send it to the customer.")
        print("3. When they run the installer, it will zero-typing auto-configure everything!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup cancelled.")
        sys.exit(0)
