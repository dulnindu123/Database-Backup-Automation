import json
import base64
import time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from admin.sign_bundle import build_bundle, sign_bundle, verify_bundle

priv_pem = b"""-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIFg/nmlec09qWVhefNJl/Mj28V8c4NcxwJ1I+L6rPcBc
-----END PRIVATE KEY-----
"""

priv = serialization.load_pem_private_key(priv_pem, password=None)
pub = priv.public_key()

with open(r'c:\Users\dulni\OneDrive\Documents\Desktop\idea\Client_Installation_Package\AppFiles\backup_public.pem', 'r', encoding='utf-8') as f:
    p_pem = f.read()

with open(r'c:\Users\dulni\OneDrive\Documents\Desktop\idea\Client_Installation_Package\AppFiles\escrow_public.pem', 'r', encoding='utf-8') as f:
    e_pem = f.read()

broker_url = "https://script.google.com/macros/s/AKfycbzyN6oeIdAxT2gZOOIuxob8X8sSwmrKiRP6BvZP-ua_CGbnxaZKBtQ7RfP7Loy8QF8xGA/exec"
slug = "fmi"
enroll_code = "FMI@spillabs.com"

b = build_bundle(slug, broker_url, p_pem, e_pem, enroll_code=enroll_code)
b64, sig = sign_bundle(priv, b)

v = verify_bundle(pub, b64, sig, expect_customer=slug)
print("SUCCESSFULLY VERIFIED BUNDLE!")
print("Customer:", v["customer"])
print("Broker URL:", v["broker_url"])
print("Enroll Code:", v.get("enroll_code"))

bundle_data = {
    "BUNDLE_B64": b64,
    "SIGNATURE_B64": sig
}

# Write bundle.json to Client_Installation_Package root
with open(r'c:\Users\dulni\OneDrive\Documents\Desktop\idea\Client_Installation_Package\bundle.json', 'w', encoding='utf-8') as f:
    json.dump(bundle_data, f, indent=2)

# Write bundle.json to AppFiles and shell_client as well
with open(r'c:\Users\dulni\OneDrive\Documents\Desktop\idea\Client_Installation_Package\AppFiles\bundle.json', 'w', encoding='utf-8') as f:
    json.dump(bundle_data, f, indent=2)

with open(r'c:\Users\dulni\OneDrive\Documents\Desktop\idea\Client_Installation_Package\shell_client\bundle.json', 'w', encoding='utf-8') as f:
    json.dump(bundle_data, f, indent=2)

print("Wrote bundle.json to Client_Installation_Package root, AppFiles, and shell_client successfully!")
