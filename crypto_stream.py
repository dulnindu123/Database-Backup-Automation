"""
DBK2 Streaming Hybrid Encryption Engine
=============================================================================
Format: AES-256-GCM per 64 KiB chunk + RSA-OAEP (SHA-256) dual key wrapping.
Client PCs only hold PUBLIC keys, guaranteeing that even complete client
compromise cannot decrypt historical or current backups.

DBK2 Header Layout (v1 with Authenticated Context Binding):
  0..3   : MAGIC b"DBK2" (4 bytes)
  4      : VERSION 0x01 (1 byte uint8)
  5      : NUM_RECIPIENTS (1 byte uint8, 1..8)
  For each recipient:
    0..7 : FINGERPRINT (8 bytes, SHA-256 prefix of SubjectPublicKeyInfo)
    8..9 : WRAPPED_KEY_LEN (2 bytes uint16 big-endian)
    ...  : WRAPPED_KEY (WRAPPED_KEY_LEN bytes, RSA-OAEP encrypted AES-256 key)
  Context Binding Block:
    1 byte   : DB_NAME_LEN (uint8) + DB_NAME (UTF-8 bytes)
    2 bytes  : FILE_NAME_LEN (uint16 big-endian) + FILE_NAME (UTF-8 bytes)
    1 byte   : HOST_LEN (uint8) + HOST_NAME (UTF-8 bytes)
    1 byte   : TIME_LEN (uint8) + UTC_ISO_TIME (UTF-8 bytes)
  Nonce Initialization:
    8 bytes  : NONCE_PREFIX (random bytes)

Chunk Stream (64 KiB plaintext blocks):
  Repeated: 4-byte uint32 len(ciphertext) | ciphertext (AES-256-GCM, 16-byte tag)
  Nonce per chunk: NONCE_PREFIX (8 bytes) + 4-byte big-endian chunk counter.
  AAD per chunk: SHA-256(Header) + Terminal Flag (0x01 final, 0x00 intermediate) + 4-byte counter.

Guarantees:
  - 1..8 recipients (Primary + Escrow required by default).
  - Minimum 3072-bit RSA keys enforced.
  - Context (database, filename, host, UTC timestamp) bound to authenticated header.
  - Zero partial output on decryption failure (atomic temp write & immediate cleanup).
"""
import os
import sys
import socket
import hashlib
import tempfile
import warnings
from datetime import datetime, timezone
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

MAGIC = b"DBK2"
VERSION = 1
MIN_RSA_KEY_BITS = 3072
MAX_RECIPIENTS = 8
CHUNK_SIZE = 64 * 1024  # 64 KiB streaming chunk size

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None
)


class DecryptionError(Exception):
    """Raised when DBK2 decryption or verification fails."""
    pass


def get_public_key_fingerprint(pub_key):
    """Computes an 8-byte SHA-256 fingerprint from SubjectPublicKeyInfo."""
    der = pub_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(der).digest()[:8]


def load_and_validate_public_key(key_path):
    """Loads a PEM public key and validates minimum key size (>= 3072 bits)."""
    with open(key_path, "rb") as f:
        data = f.read()
    pub = serialization.load_pem_public_key(data)
    if not isinstance(pub, rsa.RSAPublicKey):
        raise ValueError(f"Key {key_path} is not an RSA public key.")
    if pub.key_size < MIN_RSA_KEY_BITS:
        raise ValueError(
            f"RSA key {key_path} has size {pub.key_size} bits; minimum {MIN_RSA_KEY_BITS} bits required."
        )
    return pub


def load_and_validate_private_key(key_path, password=None):
    """Loads a PEM private key and validates minimum key size (>= 3072 bits)."""
    with open(key_path, "rb") as f:
        data = f.read()
    priv = serialization.load_pem_private_key(
        data,
        password=password.encode() if isinstance(password, str) else password
    )
    if not isinstance(priv, rsa.RSAPrivateKey):
        raise ValueError(f"Key {key_path} is not an RSA private key.")
    if priv.key_size < MIN_RSA_KEY_BITS:
        raise ValueError(
            f"RSA key {key_path} has size {priv.key_size} bits; minimum {MIN_RSA_KEY_BITS} bits required."
        )
    return priv


def encrypt_file(src, dst, public_key_paths, cancel_check=None, escrow_key_path=None,
                 allow_no_escrow=False, db_name="", host=None, utc_time=None):
    """
    Encrypts source file to destination in DBK2 format.
    Accepts a single public key path or a list of public key paths (1..8 recipients).
    If escrow_key_path is provided, it is included as an additional recipient.
    
    Escrow Requirement:
      An escrow key is mandatory by default. If no escrow key is provided and
      allow_no_escrow is False, this function raises a ValueError.
    
    Context Binding:
      The header binds db_name, file_name, host, and utc_time, which are hashed
      into the header_auth_tag and validated via AAD on every encrypted chunk.
    """
    # Normalize public keys
    if isinstance(public_key_paths, (str, bytes, os.PathLike)):
        keys = [public_key_paths]
    else:
        keys = list(public_key_paths)

    has_escrow = bool(escrow_key_path and os.path.exists(escrow_key_path))
    if has_escrow:
        if escrow_key_path not in keys:
            keys.append(escrow_key_path)
    elif not allow_no_escrow:
        raise ValueError(
            "CRITICAL SECURITY REQUIREMENT: An escrow public key is required for DBK2 encryption. "
            "If the primary key is lost or compromised, backups without escrow cannot be recovered. "
            "To override this requirement, set allow_no_escrow=True or configure ALLOW_NO_ESCROW=true."
        )
    else:
        warnings.warn(
            "SECURITY WARNING: Encrypting WITHOUT escrow public key (explicitly allowed). "
            "If the primary key is lost or corrupted, backups will be PERMANENTLY UNRECOVERABLE.",
            UserWarning,
            stacklevel=2
        )

    if not (1 <= len(keys) <= MAX_RECIPIENTS):
        raise ValueError(f"Recipient count must be between 1 and {MAX_RECIPIENTS} (got {len(keys)})")

    # Load and validate all recipient keys
    recipients = []
    for kp in keys:
        pub = load_and_validate_public_key(kp)
        fp = get_public_key_fingerprint(pub)
        recipients.append((fp, pub))

    # Generate random 256-bit AES key and 8-byte nonce prefix
    aes_key = AESGCM.generate_key(bit_length=256)
    aes = AESGCM(aes_key)
    nonce_prefix = os.urandom(8)

    # Context fields
    db_bytes = (db_name or "").encode("utf-8")[:255]
    file_bytes = os.path.basename(src).encode("utf-8")[:65535]
    host_bytes = (host or socket.gethostname()).encode("utf-8")[:255]
    time_bytes = (utc_time or datetime.now(timezone.utc).isoformat()).encode("utf-8")[:255]

    # Build Header: MAGIC (4) + VERSION (1) + NUM_RECIPIENTS (1)
    header_buf = bytearray()
    header_buf.extend(MAGIC)
    header_buf.append(VERSION)
    header_buf.append(len(recipients))

    for fp, pub in recipients:
        wrapped = pub.encrypt(aes_key, _OAEP)
        header_buf.extend(fp)
        header_buf.extend(len(wrapped).to_bytes(2, "big"))
        header_buf.extend(wrapped)

    # Context block
    header_buf.append(len(db_bytes))
    header_buf.extend(db_bytes)
    header_buf.extend(len(file_bytes).to_bytes(2, "big"))
    header_buf.extend(file_bytes)
    header_buf.append(len(host_bytes))
    header_buf.extend(host_bytes)
    header_buf.append(len(time_bytes))
    header_buf.extend(time_bytes)

    # Nonce prefix
    header_buf.extend(nonce_prefix)
    header_bytes = bytes(header_buf)
    header_auth_tag = hashlib.sha256(header_bytes).digest()

    dst_tmp = dst + ".tmp"
    try:
        with open(src, "rb") as fi, open(dst_tmp, "wb") as fo:
            fo.write(header_bytes)

            counter = 0
            cur_chunk = fi.read(CHUNK_SIZE)
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError("Encryption cancelled by user")

                next_chunk = fi.read(CHUNK_SIZE)
                is_last = not next_chunk

                # Nonce = 8-byte prefix + 4-byte counter
                nonce = nonce_prefix + counter.to_bytes(4, "big")
                # AAD binds header hash, last-chunk flag, and counter
                aad = header_auth_tag + (b"\x01" if is_last else b"\x00") + counter.to_bytes(4, "big")

                ciphertext = aes.encrypt(nonce, cur_chunk, aad)
                fo.write(len(ciphertext).to_bytes(4, "big"))
                fo.write(ciphertext)

                if is_last:
                    break

                cur_chunk = next_chunk
                counter += 1

            fo.flush()
            os.fsync(fo.fileno())

        # Atomic replace
        if os.path.exists(dst):
            os.remove(dst)
        os.replace(dst_tmp, dst)
        return {
            "db": db_bytes.decode("utf-8"),
            "db_name": db_bytes.decode("utf-8"),
            "file_name": file_bytes.decode("utf-8"),
            "host": host_bytes.decode("utf-8"),
            "utc_time": time_bytes.decode("utf-8")
        }

    except Exception:
        if os.path.exists(dst_tmp):
            try:
                os.remove(dst_tmp)
            except Exception:
                pass
        raise


def decrypt_file(src, dst, private_key_path, password=None, cancel_check=None):
    """
    Decrypts a DBK2 archive using the provided private key (Primary or Escrow).
    Operates atomically: on ANY tampering, MAC failure, or corruption,
    the temporary output is deleted immediately, leaving NO partial output on disk.
    
    Returns a dict with context metadata (db, file_name, host, utc_time) on success.
    """
    priv = load_and_validate_private_key(private_key_path, password=password)
    my_fp = get_public_key_fingerprint(priv.public_key())

    total_size = os.path.getsize(src)
    dst_tmp = dst + ".tmp"

    try:
        with open(src, "rb") as fi:
            # 1. Parse and validate header
            magic = fi.read(4)
            if magic != MAGIC:
                raise DecryptionError(f"Invalid file format: expected {MAGIC!r}, got {magic!r}")

            ver = fi.read(1)
            if not ver or ver[0] != VERSION:
                raise DecryptionError(f"Unsupported DBK2 version: {ord(ver) if ver else 'EOF'}")

            nrec_byte = fi.read(1)
            if not nrec_byte or not (1 <= nrec_byte[0] <= MAX_RECIPIENTS):
                raise DecryptionError(f"Invalid recipient count in header: {ord(nrec_byte) if nrec_byte else 'EOF'}")
            num_recipients = nrec_byte[0]

            matched_wrapped_key = None
            all_wrapped_keys = []

            for _ in range(num_recipients):
                fp = fi.read(8)
                klen_bytes = fi.read(2)
                if len(fp) < 8 or len(klen_bytes) < 2:
                    raise DecryptionError("Truncated DBK2 recipient header")
                klen = int.from_bytes(klen_bytes, "big")
                wrapped = fi.read(klen)
                if len(wrapped) < klen:
                    raise DecryptionError("Truncated DBK2 wrapped key")

                all_wrapped_keys.append(wrapped)
                if fp == my_fp:
                    matched_wrapped_key = wrapped

            # Parse Context Block
            db_len_b = fi.read(1)
            if not db_len_b:
                raise DecryptionError("Truncated DBK2 context header (db_len)")
            db_len = db_len_b[0]
            db_bytes = fi.read(db_len)

            fn_len_b = fi.read(2)
            if len(fn_len_b) < 2:
                raise DecryptionError("Truncated DBK2 context header (fn_len)")
            fn_len = int.from_bytes(fn_len_b, "big")
            file_bytes = fi.read(fn_len)

            host_len_b = fi.read(1)
            if not host_len_b:
                raise DecryptionError("Truncated DBK2 context header (host_len)")
            host_len = host_len_b[0]
            host_bytes = fi.read(host_len)

            time_len_b = fi.read(1)
            if not time_len_b:
                raise DecryptionError("Truncated DBK2 context header (time_len)")
            time_len = time_len_b[0]
            time_bytes = fi.read(time_len)

            nonce_prefix = fi.read(8)
            if len(nonce_prefix) < 8:
                raise DecryptionError("Truncated DBK2 nonce prefix")

            # Reconstruct header bytes to verify AAD
            header_end_pos = fi.tell()
            fi.seek(0)
            header_bytes = fi.read(header_end_pos)
            header_auth_tag = hashlib.sha256(header_bytes).digest()

            # 2. Decrypt AES key (try matched fingerprint first, then fallback to trial decrypt)
            aes_key = None
            if matched_wrapped_key:
                try:
                    aes_key = priv.decrypt(matched_wrapped_key, _OAEP)
                except Exception:
                    pass

            if not aes_key:
                for cand in all_wrapped_keys:
                    try:
                        aes_key = priv.decrypt(cand, _OAEP)
                        if aes_key:
                            break
                    except Exception:
                        continue

            if not aes_key:
                raise DecryptionError("Decryption failed: provided private key does not match any recipient in this backup.")

            aes = AESGCM(aes_key)

            # 3. Decrypt streaming chunks with atomic output
            with open(dst_tmp, "wb") as fo:
                counter = 0
                while True:
                    if cancel_check and cancel_check():
                        raise InterruptedError("Decryption cancelled by user")

                    len_bytes = fi.read(4)
                    if not len_bytes:
                        raise DecryptionError("Unexpected EOF: missing terminal chunk (stream truncated)")
                    if len(len_bytes) < 4:
                        raise DecryptionError("Truncated chunk length header")

                    chunk_len = int.from_bytes(len_bytes, "big")
                    ct = fi.read(chunk_len)
                    if len(ct) < chunk_len:
                        raise DecryptionError("Truncated ciphertext chunk")

                    is_last = (fi.tell() == total_size)
                    nonce = nonce_prefix + counter.to_bytes(4, "big")
                    aad = header_auth_tag + (b"\x01" if is_last else b"\x00") + counter.to_bytes(4, "big")

                    # Will raise cryptography.exceptions.InvalidTag on any tampering
                    try:
                        pt = aes.decrypt(nonce, ct, aad)
                    except InvalidTag:
                        raise DecryptionError(f"Integrity check failed: chunk #{counter} ciphertext or header tag was tampered with.")
                    fo.write(pt)

                    if is_last:
                        break
                    counter += 1

                fo.flush()
                os.fsync(fo.fileno())

        # Decryption verified cleanly: atomic promote
        if os.path.exists(dst):
            os.remove(dst)
        os.replace(dst_tmp, dst)

        return {
            "db": db_bytes.decode("utf-8", errors="replace"),
            "db_name": db_bytes.decode("utf-8", errors="replace"),
            "file_name": file_bytes.decode("utf-8", errors="replace"),
            "host": host_bytes.decode("utf-8", errors="replace"),
            "utc_time": time_bytes.decode("utf-8", errors="replace")
        }

    except Exception:
        # Atomic guarantee: never leave partial/corrupted output on failure
        if os.path.exists(dst_tmp):
            try:
                os.remove(dst_tmp)
            except Exception:
                pass
        raise
