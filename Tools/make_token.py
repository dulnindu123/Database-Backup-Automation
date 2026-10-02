"""Create a token for one PC.  usage: python make_token.py pc-office-01
Give the printed TOKEN to that PC only. Add the printed JSON line to pc_tokens.json.
Revoke a PC by deleting its line and uploading a new secret version."""
import sys, re, secrets, hashlib
pc = sys.argv[1] if len(sys.argv) > 1 else ""
if not re.match(r"^[a-z0-9-]{3,40}$", pc):
    raise SystemExit("pc id: 3-40 chars of a-z 0-9 -")
secret = secrets.token_urlsafe(32)
print("TOKEN (give to the PC, shown once):", f"{pc}.{secret}")
print("ADD TO pc_tokens.json:", f'"{pc}": "{hashlib.sha256(secret.encode()).hexdigest()}"')
