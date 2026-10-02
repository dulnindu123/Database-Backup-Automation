"""
Admin Manifest Signer & Verifier (Ed25519)
=============================================================================
Signs and verifies customer deployment manifests using Ed25519 cryptography.
The private key is stored strictly on the administrator workstation and NEVER
distributed with customer installation packages or deployed to client PCs.
The public key is embedded into the installer/preflight engine to authenticate
the manifest, customer slug, broker URL, and public encryption key fingerprints.
"""

import os
import sys
import json
import base64
import re
from typing import Dict, Any, Tuple, Optional
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

# Default paths for admin keys (workstation-only)
ADMIN_KEYS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "keys"))
PRIVATE_KEY_PATH = os.path.join(ADMIN_KEYS_DIR, "admin_ed25519_private.pem")
PUBLIC_KEY_PATH = os.path.join(ADMIN_KEYS_DIR, "admin_ed25519_public.pem")

SLUG_RE = re.compile(r"^[a-z0-9]{2,24}$")


def get_or_create_admin_keypair(key_dir: str = ADMIN_KEYS_DIR) -> Tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Loads existing admin Ed25519 keypair or generates a new one on workstation."""
    os.makedirs(key_dir, exist_ok=True)
    priv_file = os.path.join(key_dir, "admin_ed25519_private.pem")
    pub_file = os.path.join(key_dir, "admin_ed25519_public.pem")

    if os.path.exists(priv_file) and os.path.exists(pub_file):
        with open(priv_file, "rb") as f:
            priv_key = serialization.load_pem_private_key(f.read(), password=None)
        with open(pub_file, "rb") as f:
            pub_key = serialization.load_pem_public_key(f.read())
        return priv_key, pub_key

    # Generate new Ed25519 keypair
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    priv_pem = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    with open(priv_file, "wb") as f:
        f.write(priv_pem)
    with open(pub_file, "wb") as f:
        f.write(pub_pem)

    return priv_key, pub_key


def generate_ed25519_keypair() -> Tuple[Ed25519PrivateKey, str]:
    """Generates an ephemeral Ed25519 keypair and returns (private_key_obj, public_key_pem_str)."""
    priv_key = Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")
    return priv_key, pub_pem


def get_admin_public_key_pem(key_dir: str = ADMIN_KEYS_DIR) -> str:
    """Returns the PEM representation of the admin public key."""
    _, pub_key = get_or_create_admin_keypair(key_dir)
    pem_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return pem_bytes.decode("utf-8").strip()


def sign_manifest(manifest_dict: Dict[str, Any], private_key: Ed25519PrivateKey) -> Tuple[bytes, str]:
    """
    Serializes manifest to canonical JSON (sorted keys, compact separators)
    and signs it using the Ed25519 private key.
    Returns (canonical_bytes, base64_signature).
    """
    canonical_bytes = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig_bytes = private_key.sign(canonical_bytes)
    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")
    return canonical_bytes, sig_b64


def verify_manifest(
    manifest_data: Any,
    signature_b64: str,
    public_key: Optional[Ed25519PublicKey] = None,
    public_key_pem: Optional[str] = None,
    expected_slug: Optional[str] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Cryptographically verifies the Ed25519 signature of a manifest and
    validates all security constraints (HTTPS URL, slug structure, key fingerprints).
    Returns (is_valid, reason_or_message, parsed_dict).
    """
    if isinstance(manifest_data, (str, bytes)):
        try:
            raw_bytes = manifest_data.encode("utf-8") if isinstance(manifest_data, str) else manifest_data
            parsed = json.loads(raw_bytes)
            canonical_bytes = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        except Exception as e:
            return False, f"Manifest JSON parsing failed: {e}", {}
    elif isinstance(manifest_data, dict):
        parsed = manifest_data
        canonical_bytes = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    else:
        return False, "Unsupported manifest data format", {}

    # Load public key
    if public_key is None:
        if public_key_pem:
            try:
                public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            except Exception as e:
                return False, f"Invalid public key PEM: {e}", {}
        else:
            _, public_key = get_or_create_admin_keypair()

    # 1. Verify Signature
    try:
        sig_bytes = base64.b64decode(signature_b64)
        public_key.verify(sig_bytes, canonical_bytes)
    except InvalidSignature:
        return False, "Tampered package: Ed25519 manifest signature is invalid!", parsed
    except Exception as e:
        return False, f"Signature verification error: {e}", parsed

    # 2. Validate Schema & Constraints
    for required_field in ("customer_slug", "broker_url", "version", "expected_key_fingerprints"):
        if required_field not in parsed:
            return False, f"Manifest missing mandatory field '{required_field}'", parsed

    slug = parsed.get("customer_slug", "")
    if not SLUG_RE.match(slug):
        return False, f"Invalid customer slug format in manifest: '{slug}'", parsed

    if expected_slug and slug != expected_slug:
        return False, f"Customer slug mismatch: manifest is for '{slug}', expected '{expected_slug}'", parsed

    # 3. HTTPS URL Validation
    broker_url = parsed.get("broker_url", "")
    parsed_url = urlparse(broker_url)
    if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
        return False, f"Insecure or invalid broker URL in manifest: '{broker_url}' (HTTPS required)", parsed

    # 4. Key Fingerprints Validation
    fps = parsed.get("expected_key_fingerprints", [])
    if not isinstance(fps, list) or len(fps) < 2 or len(set(fps)) < 2:
        return False, "Manifest must specify at least 2 distinct public key fingerprints", parsed

    return True, "Manifest signature and constraints verified successfully", parsed
