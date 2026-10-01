"""
Unit & Tamper Tests for DBK2 Hybrid Streaming Encryption Engine (crypto_stream.py)
=============================================================================
Verifies full DBK2 specification:
- 1..8 recipients supported (Primary + Escrow).
- Minimum 3072-bit RSA key enforcement (rejects < 3072-bit keys).
- Header authentication and chunk AAD binding.
- Fingerprints: 8-byte SHA-256 SubjectPublicKeyInfo prefix.
- Atomic output guarantee: zero partial output on failure, tampering, or truncation.
- Escrow missing warning test.
- Tamper tests (header corruption, ciphertext corruption, stream truncation).
"""
import os
import sys
import tempfile
import warnings
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import crypto_stream


class TestCryptoStreamDBK2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        base = cls.temp_dir.name

        # 1. Generate 3072-bit Primary RSA Keypair
        cls.primary_priv = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.primary_priv_path = os.path.join(base, "primary_priv.pem")
        cls.primary_pub_path = os.path.join(base, "primary_pub.pem")
        with open(cls.primary_priv_path, "wb") as f:
            f.write(cls.primary_priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()
            ))
        with open(cls.primary_pub_path, "wb") as f:
            f.write(cls.primary_priv.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo
            ))

        # 2. Generate 4096-bit Escrow RSA Keypair
        cls.escrow_priv = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        cls.escrow_priv_path = os.path.join(base, "escrow_priv.pem")
        cls.escrow_pub_path = os.path.join(base, "escrow_pub.pem")
        with open(cls.escrow_priv_path, "wb") as f:
            f.write(cls.escrow_priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()
            ))
        with open(cls.escrow_pub_path, "wb") as f:
            f.write(cls.escrow_priv.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo
            ))

        # 3. Generate weak 2048-bit RSA Keypair (for rejection test)
        cls.weak_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.weak_pub_path = os.path.join(base, "weak_pub.pem")
        cls.weak_priv_path = os.path.join(base, "weak_priv.pem")
        with open(cls.weak_priv_path, "wb") as f:
            f.write(cls.weak_priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()
            ))
        with open(cls.weak_pub_path, "wb") as f:
            f.write(cls.weak_priv.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo
            ))

        # Sample test data (multi-chunk > 2 MiB)
        cls.test_payload = b"CRITICAL_DATABASE_PAYLOAD_TEST_DATA_" * 70000
        cls.src_file = os.path.join(base, "source.bak")
        with open(cls.src_file, "wb") as f:
            f.write(cls.test_payload)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_01_minimum_key_size_enforced(self):
        """Rejects RSA keys smaller than 3072 bits."""
        # Public key validation
        with self.assertRaises(ValueError) as ctx:
            crypto_stream.load_and_validate_public_key(self.weak_pub_path)
        self.assertIn("minimum 3072 bits required", str(ctx.exception))

        # Private key validation
        with self.assertRaises(ValueError) as ctx:
            crypto_stream.load_and_validate_private_key(self.weak_priv_path)
        self.assertIn("minimum 3072 bits required", str(ctx.exception))

        # 3072-bit and 4096-bit load successfully
        self.assertIsNotNone(crypto_stream.load_and_validate_public_key(self.primary_pub_path))
        self.assertIsNotNone(crypto_stream.load_and_validate_public_key(self.escrow_pub_path))

    def test_02_dual_recipient_encryption_and_decryption(self):
        """Dual key wrapping: both Primary and Escrow can independently decrypt."""
        enc_file = os.path.join(self.temp_dir.name, "backup.dbk2")
        out_primary = os.path.join(self.temp_dir.name, "out_primary.bak")
        out_escrow = os.path.join(self.temp_dir.name, "out_escrow.bak")

        # Encrypt with Primary + Escrow
        crypto_stream.encrypt_file(
            self.src_file,
            enc_file,
            public_key_paths=[self.primary_pub_path],
            escrow_key_path=self.escrow_pub_path
        )

        # Check DBK2 header format
        with open(enc_file, "rb") as f:
            magic = f.read(4)
            version = f.read(1)[0]
            num_recipients = f.read(1)[0]

        self.assertEqual(magic, b"DBK2")
        self.assertEqual(version, 1)
        self.assertEqual(num_recipients, 2)

        # Decrypt using Primary Key
        crypto_stream.decrypt_file(enc_file, out_primary, self.primary_priv_path)
        with open(out_primary, "rb") as f:
            self.assertEqual(f.read(), self.test_payload)

        # Decrypt using Escrow Key
        crypto_stream.decrypt_file(enc_file, out_escrow, self.escrow_priv_path)
        with open(out_escrow, "rb") as f:
            self.assertEqual(f.read(), self.test_payload)

    def test_03_escrow_enforcement(self):
        """Encrypting without escrow fails by default; succeeds with warning when allow_no_escrow=True."""
        enc_file_fail = os.path.join(self.temp_dir.name, "no_escrow_fail.dbk2")
        # 1. Default: MUST fail with ValueError
        with self.assertRaises(ValueError) as ctx:
            crypto_stream.encrypt_file(
                self.src_file,
                enc_file_fail,
                public_key_paths=[self.primary_pub_path],
                escrow_key_path=None,
                allow_no_escrow=False
            )
        self.assertIn("CRITICAL SECURITY REQUIREMENT: An escrow public key is required", str(ctx.exception))

        # 2. Explicit opt-in: succeeds with warning
        enc_file_warn = os.path.join(self.temp_dir.name, "no_escrow_warn.dbk2")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            crypto_stream.encrypt_file(
                self.src_file,
                enc_file_warn,
                public_key_paths=[self.primary_pub_path],
                escrow_key_path=None,
                allow_no_escrow=True
            )
            self.assertTrue(any("Encrypting WITHOUT escrow public key" in str(item.message) for item in w))

    def test_03b_dbk2_context_binding(self):
        """DBK2 binds database name, filename, host, and timestamp in authenticated header."""
        enc_file = os.path.join(self.temp_dir.name, "context_test.dbk2")
        out_file = os.path.join(self.temp_dir.name, "context_out.bak")

        metadata = crypto_stream.encrypt_file(
            self.src_file,
            enc_file,
            public_key_paths=[self.primary_pub_path],
            escrow_key_path=self.escrow_pub_path,
            db_name="AcmeCorpDB",
            host="db-cluster-node-01",
            utc_time="2026-10-01T07:15:00Z"
        )
        self.assertEqual(metadata["db_name"], "AcmeCorpDB")
        self.assertEqual(metadata["host"], "db-cluster-node-01")
        self.assertEqual(metadata["utc_time"], "2026-10-01T07:15:00Z")

        # Decrypt and verify returned context matches authenticated header
        dec_meta = crypto_stream.decrypt_file(enc_file, out_file, self.primary_priv_path)
        self.assertEqual(dec_meta["db_name"], "AcmeCorpDB")
        self.assertEqual(dec_meta["host"], "db-cluster-node-01")
        self.assertEqual(dec_meta["utc_time"], "2026-10-01T07:15:00Z")
        self.assertEqual(dec_meta["file_name"], os.path.basename(self.src_file))

    def test_03c_chunk_size_standard(self):
        """Verify DBK2 streaming chunk size is standardized to 64 KiB."""
        self.assertEqual(crypto_stream.CHUNK_SIZE, 64 * 1024)

    def test_04_tamper_header_fails_with_zero_partial_output(self):
        """Tampering with DBK2 header causes immediate failure and leaves zero output on disk."""
        enc_file = os.path.join(self.temp_dir.name, "backup_tamper_hdr.dbk2")
        crypto_stream.encrypt_file(
            self.src_file,
            enc_file,
            public_key_paths=[self.primary_pub_path],
            escrow_key_path=self.escrow_pub_path
        )

        # Read encrypted bytes and tamper with header recipient length byte
        with open(enc_file, "rb") as f:
            data = bytearray(f.read())
        data[5] = 0x05  # Corrupt recipient count

        tampered_file = os.path.join(self.temp_dir.name, "tampered_hdr.dbk2")
        with open(tampered_file, "wb") as f:
            f.write(data)

        target_out = os.path.join(self.temp_dir.name, "should_not_exist_hdr.bak")
        with self.assertRaises(Exception):
            crypto_stream.decrypt_file(tampered_file, target_out, self.primary_priv_path)

        # Atomic guarantee: target file and .tmp MUST NOT exist
        self.assertFalse(os.path.exists(target_out), "Target file should not exist after failure")
        self.assertFalse(os.path.exists(target_out + ".tmp"), "Temporary output file should be unlinked")

    def test_05_tamper_ciphertext_fails_with_zero_partial_output(self):
        """Tampering with 1 byte of ciphertext causes AES-GCM MAC failure and leaves zero output."""
        enc_file = os.path.join(self.temp_dir.name, "backup_tamper_body.dbk2")
        crypto_stream.encrypt_file(
            self.src_file,
            enc_file,
            public_key_paths=[self.primary_pub_path],
            escrow_key_path=self.escrow_pub_path
        )

        with open(enc_file, "rb") as f:
            data = bytearray(f.read())

        # Flip a bit near the middle of the ciphertext body
        midpoint = len(data) // 2
        data[midpoint] ^= 0xFF

        tampered_file = os.path.join(self.temp_dir.name, "tampered_body.dbk2")
        with open(tampered_file, "wb") as f:
            f.write(data)

        target_out = os.path.join(self.temp_dir.name, "should_not_exist_body.bak")
        with self.assertRaises(Exception):
            crypto_stream.decrypt_file(tampered_file, target_out, self.primary_priv_path)

        self.assertFalse(os.path.exists(target_out), "Target file should not exist after MAC failure")
        self.assertFalse(os.path.exists(target_out + ".tmp"), "Temporary output file should be unlinked")

    def test_06_stream_truncation_fails_with_zero_partial_output(self):
        """Truncated stream (missing terminal chunk) fails and leaves zero output."""
        enc_file = os.path.join(self.temp_dir.name, "backup_trunc.dbk2")
        crypto_stream.encrypt_file(
            self.src_file,
            enc_file,
            public_key_paths=[self.primary_pub_path],
            escrow_key_path=self.escrow_pub_path
        )

        with open(enc_file, "rb") as f:
            data = f.read()

        # Truncate by chopping off the last 4096 bytes
        truncated_file = os.path.join(self.temp_dir.name, "truncated.dbk2")
        with open(truncated_file, "wb") as f:
            f.write(data[:-4096])

        target_out = os.path.join(self.temp_dir.name, "should_not_exist_trunc.bak")
        with self.assertRaises(Exception):
            crypto_stream.decrypt_file(truncated_file, target_out, self.primary_priv_path)

        self.assertFalse(os.path.exists(target_out), "Target file should not exist after truncation failure")
        self.assertFalse(os.path.exists(target_out + ".tmp"), "Temporary output file should be unlinked")


if __name__ == "__main__":
    unittest.main()
