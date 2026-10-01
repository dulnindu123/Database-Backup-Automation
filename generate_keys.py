"""Run ONCE on a secure, offline workstation. Never on a server or user PC.
Copy ONLY backup_public.pem to the app folder. Store the private key + passphrase
in at least two separate offline locations (e.g. encrypted USB in a safe)."""
import getpass
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

pw = getpass.getpass("Choose a strong passphrase for the private key: ")
if pw != getpass.getpass("Repeat passphrase: ") or len(pw) < 14:
    raise SystemExit("Passphrases differ or shorter than 14 characters.")
key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
open("backup_private.pem", "wb").write(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.BestAvailableEncryption(pw.encode())))
open("backup_public.pem", "wb").write(key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
print("Created backup_private.pem (KEEP OFFLINE) and backup_public.pem (give to app).")
