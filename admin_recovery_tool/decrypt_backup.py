"""
Admin Disaster Recovery CLI Tool (v4.2.0)
=============================================================================
RESTRICTED: Internal Admin Workstation Tool Only (Air-Gapped Disaster Recovery).
Never distribute this tool or private keys to customer machines.

Usage:
  python decrypt_backup.py <encrypted.dbk2> <output.zip> <private_key.pem> [passphrase]
"""
import sys
import os
import getpass

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from crypto_stream import decrypt_file, DecryptionError


def main():
    if len(sys.argv) < 4:
        print("=" * 70)
        print("  🛡️ ADMIN DISASTER RECOVERY CLI - ZERO-TRUST DECRYPTION UTILITY")
        print("=" * 70)
        print("Usage:")
        print("  python decrypt_backup.py <encrypted.dbk2> <output.zip> <private_key.pem> [passphrase]\n")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2]
    key_path = sys.argv[3]
    password = sys.argv[4] if len(sys.argv) > 4 else None

    if not os.path.exists(src):
        print(f"[ERROR] Encrypted file not found: {src}")
        sys.exit(1)
    if not os.path.exists(key_path):
        print(f"[ERROR] Private key file not found: {key_path}")
        sys.exit(1)

    print(f"[*] Decrypting: {os.path.basename(src)}")
    print(f"[*] Output:     {dst}")
    print(f"[*] Key File:   {key_path}")

    try:
        meta = decrypt_file(src, dst, key_path, password=password)
        print("\n[SUCCESS] File decrypted and 128-bit MAC tag verified.")
        if meta:
            print(f"  • Database Name : {meta.get('db')}")
            print(f"  • Host Machine  : {meta.get('host')}")
            print(f"  • UTC Timestamp : {meta.get('utc_time')}")
            print(f"  • Original File : {meta.get('file_name')}")
    except Exception as e:
        if password is None and "password" in str(e).lower():
            try:
                pw = getpass.getpass("\n[Prompt] Enter private key passphrase: ")
                meta = decrypt_file(src, dst, key_path, password=pw)
                print("\n[SUCCESS] File decrypted and 128-bit MAC tag verified.")
                if meta:
                    print(f"  • Database Name : {meta.get('db')}")
                    print(f"  • Host Machine  : {meta.get('host')}")
                    print(f"  • UTC Timestamp : {meta.get('utc_time')}")
                    print(f"  • Original File : {meta.get('file_name')}")
                return
            except Exception as e2:
                print(f"\n[FAILED] Decryption aborted: {e2}")
                sys.exit(1)
        print(f"\n[FAILED] Decryption aborted: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
