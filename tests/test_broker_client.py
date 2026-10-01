"""
Unit Tests for App-Side Broker Client (broker_client.py)
=============================================================================
Tests:
- Point 7: http://127.0.0.1 / localhost must work ONLY with ALLOW_INSECURE_BROKER=true,
  and must be rejected by default in production builds.
- Public HTTP URLs rejected unconditionally.
- Token import and DPAPI protection (with automatic wipe of plaintext raw_token.txt).
- Slot retries on 409 Conflict, warning logging, and critical alert on slot exhaustion.
- Resume after 503 HTTP error during chunk streaming.
- MD5 mismatch detection and upload rejection.
- 401 Unauthorized handling.
- DPAPI LocalMachine scope verification.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import broker_client


class TestBrokerClient(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get("ALLOW_INSECURE_BROKER")
        if "ALLOW_INSECURE_BROKER" in os.environ:
            del os.environ["ALLOW_INSECURE_BROKER"]

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["ALLOW_INSECURE_BROKER"] = self.orig_env
        elif "ALLOW_INSECURE_BROKER" in os.environ:
            del os.environ["ALLOW_INSECURE_BROKER"]

    def test_01_https_urls_accepted(self):
        """HTTPS URLs are accepted by default."""
        url = "https://upload-broker-xyz.a.run.app"
        self.assertEqual(broker_client.validate_broker_url(url), url)

    def test_02_http_rejected_in_production(self):
        """http://127.0.0.1 and http://localhost are rejected by default in production."""
        for u in ("http://127.0.0.1:8080", "http://localhost:5000", "http://127.0.0.1"):
            with self.assertRaises(ValueError) as ctx:
                broker_client.validate_broker_url(u)
            self.assertIn("rejected in production", str(ctx.exception).lower())

    def test_03_http_localhost_allowed_with_env_flag(self):
        """http://127.0.0.1 is allowed ONLY when ALLOW_INSECURE_BROKER=true."""
        os.environ["ALLOW_INSECURE_BROKER"] = "true"
        url = "http://127.0.0.1:8080"
        self.assertEqual(broker_client.validate_broker_url(url), url)

        url_local = "http://localhost:8080"
        self.assertEqual(broker_client.validate_broker_url(url_local), url_local)

    def test_04_remote_http_always_rejected(self):
        """Public or remote HTTP URLs are rejected even with ALLOW_INSECURE_BROKER=true."""
        os.environ["ALLOW_INSECURE_BROKER"] = "true"
        with self.assertRaises(ValueError) as ctx:
            broker_client.validate_broker_url("http://insecure-broker.evil.com")
        self.assertIn("only https", str(ctx.exception).lower())

    def test_05_import_and_protect_token_wipes_plaintext(self):
        """import_and_protect_token saves protected token and wipes the raw file."""
        with tempfile.TemporaryDirectory() as td:
            raw_path = os.path.join(td, "raw_token.txt")
            target_dat = os.path.join(td, "token.dpapi")

            with open(raw_path, "w", encoding="utf-8") as f:
                f.write("pc-office-01.secret998877\n")

            with patch.object(broker_client, "save_token") as mock_save:
                broker_client.import_and_protect_token(raw_path, target_dat)
                mock_save.assert_called_once_with(target_dat, "pc-office-01.secret998877")

            # Raw file MUST be deleted/wiped
            self.assertFalse(os.path.exists(raw_path), "raw_token.txt should be wiped after DPAPI import")

    def test_06_slot_iteration_and_alerts_on_409(self):
        """Retries slots 1, 2, 3 on 409; logs warning; raises critical alert on 3 exhausted slots."""
        logs = []
        def mock_log(msg, level="info"):
            logs.append((level, msg))

        with tempfile.TemporaryDirectory() as td:
            dummy_file = os.path.join(td, "backup.dbk2")
            with open(dummy_file, "wb") as f:
                f.write(b"SAMPLE_DBK2_PAYLOAD" * 50)

            token_file = os.path.join(td, "token.dpapi")
            with open(token_file, "wb") as f:
                f.write(b"dummy")

            config = {
                "BROKER_URL": "https://broker.example.com",
                "BROKER_TOKEN_FILE": "token.dpapi"
            }

            # Simulate all slots returning 409 Conflict
            with patch.object(broker_client, "load_token", return_value="pc.secret"):
                mock_resp = MagicMock()
                mock_resp.status_code = 409
                with patch.object(broker_client, "request_session", return_value=mock_resp):
                    result = broker_client.secure_upload(
                        dummy_file, "UserDB", config, td, log_cb=mock_log
                    )

            self.assertIsNone(result)

            # Check that warning was logged for each slot
            slot_warnings = [m for lvl, m in logs if lvl == "warning" and "HTTP 409 Conflict" in m]
            self.assertEqual(len(slot_warnings), 3, f"Expected 3 slot warnings, got: {slot_warnings}")

            # Check that critical alert was raised
            crit_alerts = [m for lvl, m in logs if lvl == "critical" and "SECURITY ALERT" in m]
            self.assertEqual(len(crit_alerts), 1, "Should log a critical security alert on slot exhaustion")

    def test_07_resume_after_503(self):
        """Simulates 503 transient error during GCS chunk PUT and verifies resume via _query_offset."""
        logs = []
        def mock_log(msg, level="info"):
            logs.append((level, msg))

        with tempfile.TemporaryDirectory() as td:
            dummy_file = os.path.join(td, "backup.dbk2")
            test_data = b"ABCDEFGH" * 1024
            with open(dummy_file, "wb") as f:
                f.write(test_data)
            total_size = len(test_data)

            # Mock put responses: first attempt 503, second attempt 200
            resp_503 = MagicMock()
            resp_503.status_code = 503

            resp_200 = MagicMock()
            resp_200.status_code = 200
            resp_200.json.return_value = {"md5Hash": broker_client._md5_b64(dummy_file)}

            # Query offset returns 0
            with patch("requests.put", side_effect=[resp_503, resp_200]):
                with patch("time.sleep", return_value=None):
                    with patch.object(broker_client, "_query_offset", return_value=(0, None)):
                        resp = broker_client._put_all(
                            "https://storage.googleapis.com/upload/session",
                            dummy_file, total_size, mock_log, None, None, None
                        )
                        self.assertIsNotNone(resp)
                        self.assertEqual(resp.status_code, 200)

    def test_08_md5_mismatch_fails_upload(self):
        """Simulates remote MD5 differing from local file MD5, rejecting upload."""
        logs = []
        def mock_log(msg, level="info"):
            logs.append((level, msg))

        with tempfile.TemporaryDirectory() as td:
            dummy_file = os.path.join(td, "backup.dbk2")
            with open(dummy_file, "wb") as f:
                f.write(b"CORRECT_DATA_CHUNKS")

            token_file = os.path.join(td, "token.dpapi")
            with open(token_file, "wb") as f:
                f.write(b"dummy")

            config = {
                "BROKER_URL": "https://broker.example.com",
                "BROKER_TOKEN_FILE": "token.dpapi"
            }

            session_resp = MagicMock()
            session_resp.status_code = 200
            session_resp.json.return_value = {
                "session_uri": "https://upload.example.com",
                "object": "backups/pc/db/20261001_1.dbk2"
            }

            gcs_resp = MagicMock()
            gcs_resp.status_code = 200
            # Return wrong MD5 hash
            gcs_resp.json.return_value = {"md5Hash": "WRONG_INCORRECT_HASH=="}

            with patch.object(broker_client, "load_token", return_value="pc.secret"):
                with patch.object(broker_client, "request_session", return_value=session_resp):
                    with patch.object(broker_client, "_put_all", return_value=gcs_resp):
                        res = broker_client.secure_upload(
                            dummy_file, "TestDB", config, td, log_cb=mock_log
                        )
                        self.assertIsNone(res)
                        crit_errors = [m for lvl, m in logs if lvl == "critical" and "Integrity check FAILED" in m]
                        self.assertEqual(len(crit_errors), 1)

    def test_09_401_unauthorized_stops_immediately(self):
        """401 Unauthorized stops immediately without attempting subsequent slots."""
        logs = []
        def mock_log(msg, level="info"):
            logs.append((level, msg))

        with tempfile.TemporaryDirectory() as td:
            dummy_file = os.path.join(td, "backup.dbk2")
            with open(dummy_file, "wb") as f:
                f.write(b"SAMPLE_DATA")

            token_file = os.path.join(td, "token.dpapi")
            with open(token_file, "wb") as f:
                f.write(b"dummy")

            config = {
                "BROKER_URL": "https://broker.example.com",
                "BROKER_TOKEN_FILE": "token.dpapi"
            }

            mock_401 = MagicMock()
            mock_401.status_code = 401
            mock_401.text = "unauthorized"

            with patch.object(broker_client, "load_token", return_value="pc.secret"):
                with patch.object(broker_client, "request_session", return_value=mock_401) as mock_req:
                    res = broker_client.secure_upload(dummy_file, "TestDB", config, td, log_cb=mock_log)
                    self.assertIsNone(res)
                    # Should be called exactly once (slot 1), not retrying slots 2 and 3
                    self.assertEqual(mock_req.call_count, 1)

    def test_10_dpapi_scope_local_machine(self):
        """Verifies CRYPTPROTECT_LOCAL_MACHINE flag is 0x4."""
        self.assertEqual(broker_client.CRYPTPROTECT_LOCAL_MACHINE, 0x4)


if __name__ == "__main__":
    unittest.main()
