"""
Unit Tests for Core Backup Engine (backup_core.py)
=============================================================================
Tests:
- Configuration loading: UTF-8 and UTF-8 with BOM (utf-8-sig)
- Broker readiness checks: is_broker_ready() with token.dpapi and escrow key
- Installer output satisfies broker_ready()
- Database name validation against SQL injection refusal
- Local zip not deleted after failed upload
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import backup_core


class TestBackupCore(unittest.TestCase):
    def test_01_config_loading_with_and_without_bom(self):
        """Loads configuration cleanly whether written in standard UTF-8 or with UTF-8 BOM."""
        sample_config = {
            "BACKUP_DIRECTORY": "C:\\Backups",
            "TARGET_DATABASES": ["AppDB", "SalesDB"],
            "BROKER_URL": "https://upload-broker.example.com",
            "BROKER_TOKEN_FILE": "token.dpapi"
        }

        with tempfile.TemporaryDirectory() as td:
            # 1. Standard UTF-8 without BOM
            path_no_bom = os.path.join(td, "config_no_bom.json")
            with open(path_no_bom, "w", encoding="utf-8") as f:
                json.dump(sample_config, f)

            cfg1 = backup_core.load_config(path_no_bom)
            self.assertEqual(cfg1["TARGET_DATABASES"], ["AppDB", "SalesDB"])

            # 2. UTF-8 with BOM
            path_bom = os.path.join(td, "config_bom.json")
            with open(path_bom, "w", encoding="utf-8-sig") as f:
                json.dump(sample_config, f)

            cfg2 = backup_core.load_config(path_bom)
            self.assertEqual(cfg2["TARGET_DATABASES"], ["AppDB", "SalesDB"])

    def test_02_is_broker_ready(self):
        """is_broker_ready requires BROKER_URL, token.dpapi, backup_public.pem, and escrow key by default."""
        with tempfile.TemporaryDirectory() as td:
            token_path = os.path.join(td, "token.dpapi")
            pubkey_path = os.path.join(td, "backup_public.pem")
            escrow_path = os.path.join(td, "escrow_public.pem")

            # Missing token file
            cfg_no_token = {"BROKER_URL": "https://broker.example.com", "BROKER_TOKEN_FILE": "token.dpapi"}
            ok, msg = backup_core.broker_ready(cfg_no_token, base_dir=td)
            self.assertFalse(ok)
            self.assertIn("token.dpapi missing", msg)

            # Missing BROKER_URL
            with open(token_path, "wb") as f:
                f.write(b"token")
            cfg_no_url = {"BROKER_URL": "", "BROKER_TOKEN_FILE": "token.dpapi"}
            ok, msg = backup_core.broker_ready(cfg_no_url, base_dir=td)
            self.assertFalse(ok)
            self.assertIn("BROKER_URL missing", msg)

            # Present token and public key, but missing escrow
            with open(pubkey_path, "wb") as f:
                f.write(b"pubkey")
            cfg_ready_no_escrow = {"BROKER_URL": "https://broker.example.com", "BROKER_TOKEN_FILE": "token.dpapi"}
            ok, msg = backup_core.broker_ready(cfg_ready_no_escrow, base_dir=td)
            self.assertFalse(ok)
            self.assertIn("escrow_public.pem missing", msg)

            # ALLOW_NO_ESCROW overrides escrow requirement
            cfg_allow_no_escrow = {"BROKER_URL": "https://broker.example.com", "BROKER_TOKEN_FILE": "token.dpapi", "ALLOW_NO_ESCROW": True}
            ok, msg = backup_core.broker_ready(cfg_allow_no_escrow, base_dir=td)
            self.assertTrue(ok)

            # With escrow key present
            with open(escrow_path, "wb") as f:
                f.write(b"escrow")
            ok, msg = backup_core.broker_ready(cfg_ready_no_escrow, base_dir=td)
            self.assertTrue(ok)

    def test_03_installer_output_satisfies_broker_ready(self):
        """Verifies that the files laid down by the installer satisfy broker_ready()."""
        with tempfile.TemporaryDirectory() as td:
            # Simulate files produced by Setup_DatabaseBackup.exe
            config = {
                "BROKER_URL": "https://upload-broker.example.com",
                "BROKER_TOKEN_FILE": "token.dpapi",
                "PUBLIC_KEY_FILE": "backup_public.pem",
                "ESCROW_KEY_FILE": "escrow_public.pem"
            }
            with open(os.path.join(td, "config.json"), "w", encoding="utf-8") as f:
                json.dump(config, f)
            with open(os.path.join(td, "token.dpapi"), "wb") as f:
                f.write(b"ENCRYPTED_DPAPI_BYTES")
            with open(os.path.join(td, "backup_public.pem"), "wb") as f:
                f.write(b"-----BEGIN PUBLIC KEY-----\n...")
            with open(os.path.join(td, "escrow_public.pem"), "wb") as f:
                f.write(b"-----BEGIN PUBLIC KEY-----\n...")

            loaded_cfg = backup_core.load_config(os.path.join(td, "config.json"))
            ok, reason = backup_core.broker_ready(loaded_cfg, base_dir=td)
            self.assertTrue(ok, f"Installer output failed broker_ready: {reason}")

    def test_04_db_name_sanitization_and_sql_injection_refusal(self):
        """Rejects database names containing illegal characters or SQL injection attempts."""
        dangerous_names = [
            "master; DROP DATABASE AppDB;--",
            "db]--",
            "db' OR 1=1--",
            "../../etc/passwd",
            "db\"--",
            "app; EXEC xp_cmdshell('dir');--",
            "db\nDROP TABLE test",
            "db\x00inject",
            "db/*comment*/",
        ]
        for bad_name in dangerous_names:
            is_valid = backup_core.is_safe_db_name(bad_name)
            self.assertFalse(is_valid, f"Database name '{bad_name}' should be rejected as unsafe")

        safe_names = ["ProductionDB", "Client_App_2026", "Accounting-DB", "DB1", "CRM.Data"]
        for good_name in safe_names:
            is_valid = backup_core.is_safe_db_name(good_name)
            self.assertTrue(is_valid, f"Database name '{good_name}' should be accepted")

    def test_05_local_zip_not_deleted_after_failed_upload(self):
        """Verifies that if secure_upload returns None, the local .zip file is preserved."""
        with tempfile.TemporaryDirectory() as td:
            fake_zip = os.path.join(td, "TestDB_20261001.zip")
            with open(fake_zip, "wb") as f:
                f.write(b"FAKE_ZIP_CONTENT")

            config = {
                "BROKER_URL": "https://broker.example.com",
                "BROKER_TOKEN_FILE": "token.dpapi",
                "TARGET_DATABASES": ["TestDB"],
                "DELETE_LOCAL_AFTER_UPLOAD": True,
                "ALLOW_NO_ESCROW": True
            }

            # Create dummy token and key
            with open(os.path.join(td, "token.dpapi"), "wb") as f:
                f.write(b"dummy")
            with open(os.path.join(td, "backup_public.pem"), "wb") as f:
                f.write(b"dummy")

            # Mock generate_and_compress_backup to return our fake_zip
            with patch("backup_core.generate_and_compress_backup", return_value=fake_zip):
                # Mock encrypt_file
                with patch("backup_core.encrypt_file", return_value=None):
                    # Mock secure_upload to fail (return None)
                    with patch("backup_core.secure_upload", return_value=None):
                        success, summary = backup_core.run_full_backup(config=config)

            # Backup should fail
            self.assertFalse(success)
            # Local .zip MUST still exist on disk!
            self.assertTrue(os.path.exists(fake_zip), "Local zip file MUST NOT be deleted after failed upload!")


if __name__ == "__main__":
    unittest.main()
