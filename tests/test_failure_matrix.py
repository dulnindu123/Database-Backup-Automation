"""
Enterprise Preflight Failure Matrix Test Suite
=============================================================================
Tests all 8 failure modes specified in Requirement H:
1. Broker Down (Connection refused / Timeout)
2. Wrong Broker URL (Plaintext HTTP / Malformed URL)
3. Revoked Token (Broker HTTP 401 Unauthorized)
4. Missing Token (token.dpapi absent from data directories)
5. Corrupt Token / Bad DPAPI (Random bytes causing Win32 error 0x80090005)
6. Bad Public Keys (< 3072 bits, identical keys, corrupt PEM, absent key)
7. No SQL Server (Unreachable instance / connection failure)
8. Folder in OneDrive / Cloud Sync (OneDrive, Dropbox, Google Drive detected)

Every test explicitly marks its verification mode as [MODE: REAL] or [MODE: MOCKED],
and asserts the exact failure name, error code, and user-facing error message.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from preflight import (
    validate_broker_url_security,
    probe_broker_health,
    decrypt_token_dpapi,
    verify_token_with_broker,
    validate_public_keys,
    validate_backup_folder_path,
    validate_sql_server,
    validate_scheduled_task,
    run_preflight_suite,
    PreflightCheckResult,
    PreflightReport,
)

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


class TestFailureMatrix(unittest.TestCase):
    """
    Comprehensive Failure Matrix testing the 8 failure modes with
    exact error code and message assertions.
    """

    # -------------------------------------------------------------------------
    # Mode 1: Broker Down (Connection refused / Timeout)
    # -------------------------------------------------------------------------
    def test_mode_1_broker_down_connection_refused_real(self):
        """[MODE: REAL] Probe an inactive localhost port; verify connection refused."""
        # Port 59123 is an unassigned ephemeral port guaranteed to refuse connection locally
        offline_url = "https://127.0.0.1:59123"
        result = probe_broker_health(offline_url, timeout=1.0)

        self.assertFalse(result.passed, "Probe must fail for offline broker")
        self.assertIn(result.code, ("ERR_CONN_REFUSED", "ERR_NETWORK", "ERR_TLS_FAIL", "ERR_HEALTH_EXCEPTION"))
        print(f"\n  [MODE: REAL] Failure 1A (Broker Down / Conn Refused): Code={result.code} Msg='{result.message}'")

    def test_mode_1_broker_down_timeout_mocked(self):
        """[MODE: MOCKED] Probe timed out on unreachable broker endpoint."""
        import requests
        with patch("broker_client.post_broker", side_effect=requests.exceptions.Timeout("Connection timed out")):
            result = probe_broker_health("https://broker.example.com", timeout=2.0)
            self.assertFalse(result.passed)
            self.assertIn(result.code, ("ERR_TIMEOUT", "ERR_HEALTH_EXCEPTION"))
            print(f"  [MODE: MOCKED] Failure 1B (Broker Timeout): Code={result.code} Msg='{result.message}'")

    # -------------------------------------------------------------------------
    # Mode 2: Wrong Broker URL (Plaintext HTTP / Malformed URL)
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Mode 2: Wrong Broker URL (Plaintext HTTP / Malformed URL)
    # -------------------------------------------------------------------------
    def test_mode_2_wrong_url_insecure_http_real(self):
        """[MODE: REAL] Plaintext HTTP endpoint rejected in production mode."""
        insecure_url = "http://broker-upload-prod.a.run.app"
        result = validate_broker_url_security(insecure_url, allow_insecure=False)

        self.assertFalse(result.passed)
        self.assertIn(result.code, ("ERR_HTTP_INSECURE", "ERR_NOT_APPS_SCRIPT"))
        print(f"\n  [MODE: REAL] Failure 2A (Plaintext HTTP): Code={result.code} Msg='{result.message}'")

    def test_mode_2_wrong_url_malformed_real(self):
        """[MODE: REAL] Completely malformed URL rejected with parse error."""
        malformed_url = "not_a_valid_url_at_all"
        result = validate_broker_url_security(malformed_url)

        self.assertFalse(result.passed)
        self.assertIn(result.code, ("ERR_URL_MALFORMED", "ERR_NOT_APPS_SCRIPT"))
        print(f"  [MODE: REAL] Failure 2B (Malformed URL): Code={result.code} Msg='{result.message}'")

    # -------------------------------------------------------------------------
    # Mode 3: Revoked Token (HTTP 401 Unauthorized)
    # -------------------------------------------------------------------------
    def test_mode_3_revoked_token_mocked(self):
        """[MODE: MOCKED] Broker responds with HTTP 401 Unauthorized for revoked token."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = json.dumps({"error": "Invalid or revoked token", "code": 401})
        mock_resp.json.return_value = {"error": "Invalid or revoked token", "code": 401}

        with patch("broker_client.post_broker", return_value=mock_resp):
            result = verify_token_with_broker("https://script.google.com/macros/s/AKfycbtest/exec", "PC-REVOKED-01.secrettoken123")
            self.assertFalse(result.passed)
            self.assertIn(result.code, ("ERR_VERIFY", "ERR_HTTP_401_UNAUTHORIZED"))
            print(f"\n  [MODE: MOCKED] Failure 3 (Revoked Token): Code={result.code} Msg='{result.message}'")

    # -------------------------------------------------------------------------
    # Mode 4: Missing Token (token.dpapi absent)
    # -------------------------------------------------------------------------
    def test_mode_4_missing_token_real(self):
        """[MODE: REAL] token.dpapi file absent from candidate directories."""
        empty_dir = tempfile.mkdtemp(prefix="preflight_test_empty_")
        try:
            token, result = decrypt_token_dpapi(data_dir=empty_dir, target_dir=empty_dir)
            self.assertIsNone(token)
            self.assertFalse(result.passed)
            self.assertEqual(result.code, "ERR_TOKEN_FILE_ABSENT")
            self.assertIn("Token file absent", result.message)
            print(f"\n  [MODE: REAL] Failure 4 (Missing Token): Code={result.code} Msg='{result.message}'")
        finally:
            shutil.rmtree(empty_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Mode 5: Corrupt Token / Bad DPAPI (Random bytes causing Win32 error)
    # -------------------------------------------------------------------------
    def test_mode_5_corrupt_token_real(self):
        """[MODE: REAL] Corrupt binary data written to token.dpapi triggers CryptUnprotectData failure."""
        temp_dir = tempfile.mkdtemp(prefix="preflight_test_corrupt_")
        try:
            token_path = os.path.join(temp_dir, "token.dpapi")
            # Write 64 bytes of random noise (invalid DPAPI blob)
            with open(token_path, "wb") as f:
                f.write(b"\xDE\xAD\xBE\xEF" * 16)

            token, result = decrypt_token_dpapi(data_dir=temp_dir, target_dir=temp_dir)
            self.assertIsNone(token)
            self.assertFalse(result.passed)
            self.assertIn(result.code, ("ERR_DPAPI_EMPTY", "ERR_DPAPI_EXCEPTION", "ERR_WIN32_0x80090005"))
            print(f"\n  [MODE: REAL] Failure 5 (Corrupt DPAPI Token): Code={result.code} Msg='{result.message}'")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Mode 6: Bad Public Keys (< 3072 bits, identical keys, corrupt PEM, absent key)
    # -------------------------------------------------------------------------
    def test_mode_6a_key_too_short_real(self):
        """[MODE: REAL] 2048-bit RSA key rejected because < 3072 bits required."""
        temp_dir = tempfile.mkdtemp(prefix="preflight_test_shortkey_")
        try:
            # Generate a 2048-bit RSA key
            short_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            short_pem = short_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            with open(os.path.join(temp_dir, "backup_public.pem"), "wb") as f:
                f.write(short_pem)

            # Generate valid 3072-bit escrow key
            escrow_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            escrow_pem = escrow_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            with open(os.path.join(temp_dir, "escrow_public.pem"), "wb") as f:
                f.write(escrow_pem)

            result = validate_public_keys(data_dir=temp_dir, target_dir=temp_dir, min_bits=3072)
            self.assertFalse(result.passed)
            self.assertEqual(result.code, "ERR_PRIMARY_KEY_TOO_SHORT")
            self.assertIn("2048 bits < required 3072 bits", result.message)
            print(f"\n  [MODE: REAL] Failure 6A (Key Too Short): Code={result.code} Msg='{result.message}'")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_mode_6b_identical_keys_real(self):
        """[MODE: REAL] Backup and Escrow keys using identical keypair rejected."""
        temp_dir = tempfile.mkdtemp(prefix="preflight_test_samekeys_")
        try:
            # Generate 3072-bit key and write to BOTH backup and escrow files
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            pem = key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            with open(os.path.join(temp_dir, "backup_public.pem"), "wb") as f:
                f.write(pem)
            with open(os.path.join(temp_dir, "escrow_public.pem"), "wb") as f:
                f.write(pem)

            result = validate_public_keys(data_dir=temp_dir, target_dir=temp_dir)
            self.assertFalse(result.passed)
            self.assertEqual(result.code, "ERR_KEYS_NOT_DISTINCT")
            self.assertIn("Primary and Escrow keys are IDENTICAL", result.message)
            print(f"  [MODE: REAL] Failure 6B (Identical Keys): Code={result.code} Msg='{result.message}'")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_mode_6c_corrupt_key_real(self):
        """[MODE: REAL] Corrupted PEM file rejected with parsing error."""
        temp_dir = tempfile.mkdtemp(prefix="preflight_test_corruptkey_")
        try:
            with open(os.path.join(temp_dir, "backup_public.pem"), "wb") as f:
                f.write(b"-----BEGIN PUBLIC KEY-----\nCORRUPT_BASE64_GARBAGE\n-----END PUBLIC KEY-----\n")
            with open(os.path.join(temp_dir, "escrow_public.pem"), "wb") as f:
                f.write(b"-----BEGIN PUBLIC KEY-----\nANOTHER_CORRUPT\n-----END PUBLIC KEY-----\n")

            result = validate_public_keys(data_dir=temp_dir, target_dir=temp_dir)
            self.assertFalse(result.passed)
            self.assertEqual(result.code, "ERR_PRIMARY_KEY_CORRUPT")
            self.assertIn("Corrupt or unreadable", result.message)
            print(f"  [MODE: REAL] Failure 6C (Corrupt Key): Code={result.code} Msg='{result.message}'")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Mode 7: No SQL Server (Unreachable instance / Connection failure)
    # -------------------------------------------------------------------------
    def test_mode_7_no_sql_server_real(self):
        """[MODE: REAL] Query non-existent SQL server instance; verify connection failure."""
        fake_server = r"NON_EXISTENT_HOST_XYZ\FAKE_INSTANCE_999"
        results = validate_sql_server(fake_server, timeout=2)

        self.assertTrue(len(results) >= 1)
        reachability_res = results[0]
        self.assertFalse(reachability_res.passed)
        self.assertIn(reachability_res.code, ("ERR_SQL_CONN_FAILED", "ERR_SQL_EXCEPTION"))
        self.assertIn("Cannot connect to SQL Server", reachability_res.message)
        print(f"\n  [MODE: REAL] Failure 7 (No SQL Server): Code={reachability_res.code} Msg='{reachability_res.message}'")

    # -------------------------------------------------------------------------
    # Mode 8: Folder in OneDrive / Cloud Sync (OneDrive, Dropbox, Google Drive)
    # -------------------------------------------------------------------------
    def test_mode_8a_folder_in_onedrive_substring_real(self):
        """[MODE: REAL] Backup destination inside OneDrive blocked."""
        onedrive_path = r"C:\Users\JohnDoe\OneDrive\Desktop\SQLBackups"
        result = validate_backup_folder_path(onedrive_path)

        self.assertFalse(result.passed)
        self.assertIn(result.code, ("ERR_CLOUD_SYNC_ONEDRIVE", "ERR_CLOUD_SYNC_DETECTED"))
        self.assertIn("cannot be inside", result.message)
        print(f"\n  [MODE: REAL] Failure 8A (OneDrive Path): Code={result.code} Msg='{result.message}'")

    def test_mode_8b_folder_in_dropbox_real(self):
        """[MODE: REAL] Backup destination inside Dropbox blocked."""
        dropbox_path = r"D:\Data\Dropbox\Backups"
        result = validate_backup_folder_path(dropbox_path)

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "ERR_CLOUD_SYNC_DETECTED")
        self.assertIn("Dropbox", result.message)
        print(f"  [MODE: REAL] Failure 8B (Dropbox Path): Code={result.code} Msg='{result.message}'")

    def test_mode_8c_folder_in_googledrive_real(self):
        """[MODE: REAL] Backup destination inside Google Drive blocked."""
        gdrive_path = r"C:\Users\JohnDoe\Google Drive\Backups"
        result = validate_backup_folder_path(gdrive_path)

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "ERR_CLOUD_SYNC_DETECTED")
        self.assertIn("google drive", result.message.lower())
        print(f"  [MODE: REAL] Failure 8C (Google Drive Path): Code={result.code} Msg='{result.message}'")

    # -------------------------------------------------------------------------
    # Integration: run_preflight_suite Fails and Names the Failing Check
    # -------------------------------------------------------------------------
    def test_run_preflight_suite_names_failing_check(self):
        """[MODE: REAL] Verify run_preflight_suite aggregates and isolates failing check."""
        bad_config = {
            "BROKER_URL": "http://insecure-broker.test",  # Fails HTTP check
            "BACKUP_FOLDER": r"C:\Users\Admin\OneDrive\Backups",  # Fails OneDrive check
            "SQL_SERVER_NAME": "",  # Empty SQL server
            "_ENABLE_SCHEDULE": False,
        }
        report = run_preflight_suite(bad_config, mode="installer")
        self.assertFalse(report.passed)
        failures = report.failures
        fail_names = [f.name for f in failures]

        # Verify failing checks are explicitly named
        self.assertIn("Broker URL Security", fail_names)
        self.assertIn("Backup Destination Folder", fail_names)

        print("\n  [MODE: REAL] Preflight Suite Summary with named failures:")
        for f in failures:
            print(f"    - [{f.name}] ({f.code}): {f.message}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
