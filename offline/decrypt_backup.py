"""
Offline Decryption & Recovery Utility for DBK2 Encrypted Backups
=============================================================================
Run this script on an AIR-GAPPED administrative workstation.
Decrypts DBK2 backup archives using either Primary or Escrow private key.

Usage:
  python decrypt_backup.py <encrypted_file.dbk2> <output_file.zip> <private_key.pem> [password]
"""
import sys
import os
import getpass
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from crypto_stream import decrypt_file


def main():
    if len(sys.argv) < 4:
        print("Usage: python decrypt_backup.py <encrypted.dbk2> <output.zip> <private_key.pem> [password]")
        sys.exit(1)

    src = sys.argv[1]
    dst = sys.argv[2]
    key_path = sys.argv[3]
    password = sys.argv[4] if len(sys.argv) > 4 else None

    if not os.path.exists(src):
        print(f"Error: Encrypted file not found: {src}")
        sys.exit(1)
    if not os.path.exists(key_path):
        print(f"Error: Private key file not found: {key_path}")
        sys.exit(1)

    print(f"Decrypting {src} -> {dst} using key {key_path}...")
    try:
        meta = decrypt_file(src, dst, key_path, password=password)
        print("SUCCESS: File decrypted and cryptographic integrity verified.")
        if meta:
            print(f"  [Context Verified] Database:      {meta.get('db')}")
            print(f"  [Context Verified] Host:          {meta.get('host')}")
            print(f"  [Context Verified] UTC Timestamp: {meta.get('utc_time')}")
            print(f"  [Context Verified] Original File: {meta.get('file_name')}")
    except Exception as e:
        if password is None and "password" in str(e).lower():
            try:
                pw = getpass.getpass("Enter private key passphrase: ")
                meta = decrypt_file(src, dst, key_path, password=pw)
                print("SUCCESS: File decrypted and cryptographic integrity verified.")
                if meta:
                    print(f"  [Context Verified] Database:      {meta.get('db')}")
                    print(f"  [Context Verified] Host:          {meta.get('host')}")
                    print(f"  [Context Verified] UTC Timestamp: {meta.get('utc_time')}")
                    print(f"  [Context Verified] Original File: {meta.get('file_name')}")
                return
            except Exception as e2:
                print(f"FAILED to decrypt file: {e2}")
                sys.exit(1)
        print(f"FAILED to decrypt file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
