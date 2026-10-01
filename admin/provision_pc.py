"""
Admin Provisioning Utility for Database Cloud Backup
=============================================================================
Run on an administrator's machine to register a new customer PC.

Usage:
  python admin/provision_pc.py --pc-id <PC_ID> [--output-dir <DIR>]

Actions:
1. Generates a cryptographically strong secret token for the given pc_id.
2. Computes the SHA-256 hash of the secret token.
3. Outputs JSON snippet to append to Secret Manager / `pc_tokens.json`.
4. Saves raw_token.txt for secure transfer; installer encrypts into token.dpapi on the customer PC.
"""
import os
import sys
import secrets
import hashlib
import json
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from broker_client import save_token


def main():
    parser = argparse.ArgumentParser(description="Provision a new PC token for Database Cloud Backup broker.")
    parser.add_argument("--pc-id", required=True, help="Unique identifier for the customer PC (e.g. pc-cust-01)")
    parser.add_argument("--output-dir", default=".", help="Output directory for raw_token.txt")
    args = parser.parse_args()

    pc_id = args.pc_id.strip()
    secret = secrets.token_hex(24)
    raw_token = f"{pc_id}.{secret}"
    token_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()

    # Write raw_token.txt for secure transfer to the customer PC.
    # CRITICAL: DPAPI tokens are tied to the local machine's LSA secrets and CANNOT
    # be generated on the admin PC for use on a client machine.
    raw_token_path = os.path.join(args.output_dir, "raw_token.txt")
    with open(raw_token_path, "w", encoding="utf-8") as f:
        f.write(raw_token.strip() + "\n")

    print("\n" + "=" * 70)
    print(f"PROVISIONING SUCCESSFUL FOR PC ID: {pc_id}")
    print("=" * 70)
    print(f"\n1. Transfer Token Generated: {raw_token_path}")
    print("   [CRITICAL SECURITY NOTICE: DPAPI MACHINE-BINDING]")
    print("   DPAPI tokens cannot be pre-encrypted on this admin workstation because")
    print("   CryptProtectData binds secrets to the local machine's LSA keys.")
    print("   ")
    print("   SECURE TRANSFER WORKFLOW:")
    print("   a) Copy 'raw_token.txt' to the customer PC using a secure channel")
    print("      (e.g., encrypted admin USB, SCP/WinSCP, or temporary secure share).")
    print("   b) Place 'raw_token.txt' alongside '1_Quick_Install.bat' or 'Update_App.bat'.")
    print("   c) Run the batch script on the customer PC. It will automatically encrypt")
    print("      the token with the customer PC's DPAPI into 'token.dpapi', and")
    print("      immediately overwrite and wipe 'raw_token.txt'.")
    print("   d) Delete this local copy of 'raw_token.txt' after deployment.")
    print(f"\n2. Add the following entry to Secret Manager / pc_tokens.json for the Upload & Telemetry Brokers:")
    print("-" * 70)
    print(json.dumps({pc_id: token_hash}, indent=2))
    print("-" * 70)


if __name__ == "__main__":
    main()
