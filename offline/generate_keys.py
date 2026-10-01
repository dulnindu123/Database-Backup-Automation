"""
Offline Key Generation Utility for Enterprise Database Cloud Backup
=============================================================================
Run this script on an AIR-GAPPED administrative workstation.
Generates:
  1. Primary Keypair: backup_public.pem (installed on client PCs) and backup_private.pem (KEPT OFFLINE)
  2. Escrow Keypair:  escrow_public.pem (installed on client PCs) and escrow_private.pem (KEPT OFFLINE)
"""
import os
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def generate_keypair(public_path, private_path):
    print(f"Generating 4096-bit RSA keypair -> {private_path}, {public_path}...")
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    
    # Save Private Key (PKCS8, PEM)
    with open(private_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    os.chmod(private_path, 0o600)

    # Save Public Key (SubjectPublicKeyInfo, PEM)
    with open(public_path, "wb") as f:
        f.write(key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    print(f"SUCCESS: Generated {public_path} and {private_path}")


def main():
    out_dir = os.path.dirname(__file__)
    generate_keypair(
        os.path.join(out_dir, "backup_public.pem"),
        os.path.join(out_dir, "backup_private.pem")
    )
    generate_keypair(
        os.path.join(out_dir, "escrow_public.pem"),
        os.path.join(out_dir, "escrow_private.pem")
    )
    print("\nIMPORTANT:")
    print("1. Deploy 'backup_public.pem' (and optionally 'escrow_public.pem') to client PCs.")
    print("2. STORE 'backup_private.pem' and 'escrow_private.pem' in an offline vault / HSM.")
    print("3. NEVER upload private keys to Cloud Run, GCS, or customer machines.")


if __name__ == "__main__":
    main()
