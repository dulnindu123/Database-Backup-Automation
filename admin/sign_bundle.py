"""
Signed customer bundle tool (replaces admin/manifest_signer.py for the Apps Script broker design).

  python sign_bundle.py init-key --out D:\\vault_keys\\admin_ed25519.pem
  python sign_bundle.py sign --key D:\\vault_keys\\admin_ed25519.pem --slug acme \\
         --url https://script.google.com/macros/s/<id>/exec --primary primary_public.pem --escrow escrow_public.pem
  -> prints BUNDLE_B64 and SIGNATURE_B64: paste them into  Vault Admin > Add customer.

Rules enforced (each one is tested):
  * the signing key is passphrase-encrypted, never auto-generated, never created inside a synced folder
  * URL must be an Apps Script web-app address (https://script.google.com/macros/s/<id>/exec)
  * two DISTINCT RSA public keys of at least 3072 bits (primary + escrow); FULL SHA-256 fingerprints
  * the verifier recomputes every fingerprint from the PEM, so a swapped key cannot hide behind a stale fingerprint
  * optional expiry; the installer verifies with the PUBLIC key embedded in the code-signed installer
  * the bundle contains NO token and NO secret
"""
import argparse, base64, getpass, hashlib, json, os, re, sys, time
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SLUG_RE = re.compile(r"^[a-z0-9]{2,24}$")
URL_RE = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]{20,200}/exec$")
MIN_RSA_BITS = 3072
MIN_PASSPHRASE = 14
SYNC_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync")


class BundleError(ValueError):
    pass


def in_sync_folder(path):
    parts = [p.lower() for p in os.path.abspath(path).replace("\\", "/").split("/")]
    return any(m in part for part in parts for m in SYNC_MARKERS)


def init_key(path, passphrase):
    if os.path.exists(path):
        raise BundleError("key file already exists; refusing to overwrite")
    if in_sync_folder(path):
        raise BundleError("refusing to create the signing key inside a cloud-synced folder (OneDrive/Dropbox/Drive)")
    if len(passphrase or "") < MIN_PASSPHRASE:
        raise BundleError(f"passphrase must be at least {MIN_PASSPHRASE} characters")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(passphrase.encode()))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with open(path + ".pub.pem", "wb") as f:
        f.write(pub)
    return pub.decode()


def load_private(path, passphrase=""):
    with open(path, "rb") as f:
        data = f.read()
    pwd = passphrase.encode() if passphrase else None
    return serialization.load_pem_private_key(data, password=pwd)


def spki_fingerprint(pem):
    pub = serialization.load_pem_public_key(pem if isinstance(pem, bytes) else pem.encode())
    if not isinstance(pub, rsa.RSAPublicKey):
        raise BundleError("only RSA encryption keys are supported")
    if pub.key_size < MIN_RSA_BITS:
        raise BundleError(f"RSA key is {pub.key_size} bits; minimum is {MIN_RSA_BITS}")
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()


def build_bundle(slug, url, primary_pem, escrow_pem, enroll_code=None, valid_days=None, now=None):
    if not SLUG_RE.match(slug or ""):
        raise BundleError("invalid customer slug")
    if not URL_RE.match(url or ""):
        raise BundleError("url must look like https://script.google.com/macros/s/<id>/exec")
    keys = []
    for name, pem in (("primary", primary_pem), ("escrow", escrow_pem)):
        keys.append({"name": name, "fingerprint": spki_fingerprint(pem), "pem": pem.decode() if isinstance(pem, bytes) else pem})
    if keys[0]["fingerprint"] == keys[1]["fingerprint"]:
        raise BundleError("primary and escrow keys are identical")
    now = int(time.time() if now is None else now)
    b = {"customer": slug, "broker_url": url, "issued_at": now, "public_keys": keys}
    if enroll_code:
        b["enroll_code"] = enroll_code
    if valid_days:
        b["expires_at"] = now + int(valid_days) * 86400
    return b


def sign_bundle(private_key, bundle):
    data = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(data).decode(), base64.b64encode(private_key.sign(data)).decode()


def verify_bundle(public_key, bundle_b64, signature_b64, expect_customer=None, now=None):
    """Signature is checked over the EXACT bytes that were signed; only then is the JSON parsed."""
    try:
        data, sig = base64.b64decode(bundle_b64, validate=True), base64.b64decode(signature_b64, validate=True)
        public_key.verify(sig, data)
    except (InvalidSignature, ValueError):
        raise BundleError("bundle signature invalid")
    b = json.loads(data)
    for k in ("customer", "broker_url", "issued_at", "public_keys"):
        if k not in b:
            raise BundleError(f"bundle missing {k}")
    if not SLUG_RE.match(b["customer"]) or (expect_customer and b["customer"] != expect_customer):
        raise BundleError("customer mismatch")
    if not URL_RE.match(b["broker_url"]):
        raise BundleError("broker_url not allowed")
    ks = b["public_keys"]
    if not isinstance(ks, list) or len(ks) < 2:
        raise BundleError("need primary and escrow keys")
    fps = set()
    for k in ks:
        real = spki_fingerprint(k["pem"])                  # recompute: a swapped PEM cannot hide behind a stale fingerprint
        if real != k.get("fingerprint"):
            raise BundleError("key fingerprint does not match its PEM")
        fps.add(real)
    if len(fps) < 2:
        raise BundleError("primary and escrow keys must be distinct")
    now = int(time.time() if now is None else now)
    if b.get("expires_at") and now > b["expires_at"]:
        raise BundleError("bundle expired")
    return b


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("init-key"); a.add_argument("--out", required=True)
    s = sub.add_parser("sign")
    for n in ("key", "slug", "url", "primary", "escrow"):
        s.add_argument("--" + n, required=True)
    s.add_argument("--valid-days", type=int)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "init-key":
            p1 = getpass.getpass("New passphrase (14+ chars): ")
            if p1 != getpass.getpass("Repeat: "):
                raise BundleError("passphrases differ")
            print("Public key (embed this in the installer):\n" + init_key(args.out, p1))
        else:
            bundle = build_bundle(args.slug, args.url, open(args.primary, "rb").read(), open(args.escrow, "rb").read(), args.valid_days)
            b64, sig = sign_bundle(load_private(args.key, getpass.getpass("Signing key passphrase: ")), bundle)
            print("BUNDLE_B64:    " + b64 + "\nSIGNATURE_B64: " + sig)
    except (BundleError, OSError, ValueError) as e:
        print("ERROR:", e, file=sys.stderr); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
