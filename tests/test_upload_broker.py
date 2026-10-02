"""
Unit & Integration Tests for Upload Broker Cloud Run Microservice (broker/main.py)
=============================================================================
Tests:
- Token authentication: Bearer format, valid token hash, unknown PC, invalid secret (401)
- Allowed databases validation (400)
- Request size bounds and type validation (400)
- Slot sequence constraint: 1, 2, 3 allowed; bad seq (0, 4) rejected (400)
- Duplicate slot collision: GCS PreconditionFailed returns 409
- Correct object naming convention: {pc}/{db}/{day}_{seq}.dbk2
- Verification probe: POST /verify (200 vs 401)
- Liveness probe: GET /healthz (200)
"""
import os
import sys
import json
import hashlib
import unittest
import importlib.util
from unittest.mock import patch, MagicMock

# Ensure google.cloud.storage and PreconditionFailed can be imported in local unit test environment
try:
    from google.cloud import storage
    from google.api_core.exceptions import PreconditionFailed
except ImportError:
    import types
    if "google" not in sys.modules:
        sys.modules["google"] = types.ModuleType("google")
    if "google.cloud" not in sys.modules:
        sys.modules["google.cloud"] = types.ModuleType("google.cloud")
    if "google.cloud.storage" not in sys.modules:
        mock_storage = types.ModuleType("google.cloud.storage")
        mock_storage.Client = MagicMock
        sys.modules["google.cloud.storage"] = mock_storage
        sys.modules["google.cloud"].storage = mock_storage
    if "google.api_core" not in sys.modules:
        sys.modules["google.api_core"] = types.ModuleType("google.api_core")
    if "google.api_core.exceptions" not in sys.modules:
        class PreconditionFailed(Exception):
            pass
        mock_exc = types.ModuleType("google.api_core.exceptions")
        mock_exc.PreconditionFailed = PreconditionFailed
        sys.modules["google.api_core.exceptions"] = mock_exc
        sys.modules["google.api_core"].exceptions = mock_exc
    from google.api_core.exceptions import PreconditionFailed

# Dynamically import broker/main.py to avoid module collisions
broker_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "broker", "main.py"))
spec = importlib.util.spec_from_file_location("upload_broker_main", broker_main_path)
broker_main = importlib.util.module_from_spec(spec)
sys.modules["upload_broker_main"] = broker_main
spec.loader.exec_module(broker_main)


class TestUploadBroker(unittest.TestCase):
    def setUp(self):
        self.app = broker_main.app
        self.client = self.app.test_client()

        # Temporary tokens file
        self.tokens_path = os.path.join(os.path.dirname(__file__), "test_pc_tokens.json")
        self.pc_id = "pc-cust-01"
        self.secret = "abcdef1234567890abcdef12"
        secret_hash = hashlib.sha256(self.secret.encode("utf-8")).hexdigest()

        with open(self.tokens_path, "w", encoding="utf-8") as f:
            json.dump({self.pc_id: secret_hash}, f)

        broker_main.TOKENS_FILE = self.tokens_path
        broker_main.BUCKET = "test-backup-bucket"
        broker_main.ALLOWED_DBS = set()
        broker_main.CUSTOMER_SLUG = ""
        broker_main.MAX_BYTES = 50 * 1024 * 1024 * 1024  # 50 GB

    def tearDown(self):
        broker_main.ALLOWED_DBS = set()
        broker_main.CUSTOMER_SLUG = ""
        if os.path.exists(self.tokens_path):
            try:
                os.remove(self.tokens_path)
            except Exception:
                pass

    def auth_header(self, pc_id=None, secret=None):
        p = pc_id or self.pc_id
        s = secret or self.secret
        return {"Authorization": f"Bearer {p}.{s}"}

    def test_01_healthz(self):
        """GET /healthz returns 200 ok."""
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)

    def test_02_auth_rejections(self):
        """Rejects missing, malformed, unknown, or incorrect bearer tokens."""
        # Missing auth
        res = self.client.post("/request-upload", json={"db": "MainDB", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 401)

        # Bad format
        res = self.client.post("/request-upload", headers={"Authorization": "Basic dXNlcjpwYXNz"},
                               json={"db": "MainDB", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 401)

        # Unknown pc_id
        res = self.client.post("/request-upload", headers=self.auth_header(pc_id="unknown-pc"),
                               json={"db": "MainDB", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 401)

        # Wrong secret
        res = self.client.post("/request-upload", headers=self.auth_header(secret="wrong_secret_123"),
                               json={"db": "MainDB", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 401)

    def test_03_db_filtering(self):
        """Rejects databases outside ALLOWED_DBS when not set to 'all'."""
        broker_main.ALLOWED_DBS = {"ProductionDB", "ReportingDB"}

        # Allowed DB
        with patch.object(broker_main, "get_storage_client") as mock_storage:
            mock_blob = MagicMock()
            mock_blob.create_resumable_upload_session.return_value = "https://gcs/session_123"
            mock_storage.return_value.bucket.return_value.blob.return_value = mock_blob

            res = self.client.post("/request-upload", headers=self.auth_header(),
                                   json={"db": "ProductionDB", "size": 1024, "seq": 1})
            self.assertEqual(res.status_code, 200)

        # Disallowed DB
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "SecretAdminDB", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 400)
        self.assertIn("db not allowed", res.get_json().get("error", ""))
        broker_main.ALLOWED_DBS = set()

    def test_04_size_validation(self):
        """Rejects zero, negative, boolean, non-integer, or oversized payloads."""
        # Zero size
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "MainDB", "size": 0, "seq": 1})
        self.assertEqual(res.status_code, 400)

        # Negative size
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "MainDB", "size": -50, "seq": 1})
        self.assertEqual(res.status_code, 400)

        # Boolean (bool is subclass of int in Python)
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "MainDB", "size": True, "seq": 1})
        self.assertEqual(res.status_code, 400)

        # Oversized
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "MainDB", "size": broker_main.MAX_BYTES + 1, "seq": 1})
        self.assertEqual(res.status_code, 400)

    def test_05_slot_sequence_rules(self):
        """Slots 1, 2, 3 are valid; seq 0, 4 are rejected."""
        with patch.object(broker_main, "get_storage_client") as mock_storage:
            mock_blob = MagicMock()
            mock_blob.create_resumable_upload_session.return_value = "https://gcs/session_123"
            mock_storage.return_value.bucket.return_value.blob.return_value = mock_blob

            for seq in (1, 2, 3):
                res = self.client.post("/request-upload", headers=self.auth_header(),
                                       json={"db": "MainDB", "size": 1024, "seq": seq})
                self.assertEqual(res.status_code, 200, f"Slot {seq} should be valid")

        # Invalid seq
        for bad_seq in (0, 4, 99):
            res = self.client.post("/request-upload", headers=self.auth_header(),
                                   json={"db": "MainDB", "size": 1024, "seq": bad_seq})
            self.assertEqual(res.status_code, 400)

    def test_06_duplicate_slot_returns_409(self):
        """When GCS raises PreconditionFailed (if_generation_match=0), returns 409 Conflict."""
        with patch.object(broker_main, "get_storage_client") as mock_storage:
            mock_blob = MagicMock()
            mock_blob.create_resumable_upload_session.side_effect = PreconditionFailed("Object exists")
            mock_storage.return_value.bucket.return_value.blob.return_value = mock_blob

            res = self.client.post("/request-upload", headers=self.auth_header(),
                                   json={"db": "MainDB", "size": 1024, "seq": 1})
            self.assertEqual(res.status_code, 409)
            self.assertIn("already uploaded", res.get_json().get("error", ""))

    def test_07_object_naming_convention(self):
        """Ensures object name ends with .dbk2 and follows {pc}/{db}/{day}_{seq}.dbk2."""
        with patch.object(broker_main, "get_storage_client") as mock_storage:
            mock_blob = MagicMock()
            mock_blob.create_resumable_upload_session.return_value = "https://gcs/session_123"
            mock_storage.return_value.bucket.return_value.blob.return_value = mock_blob

            res = self.client.post("/request-upload", headers=self.auth_header(),
                                   json={"db": "TestDB", "size": 2048, "seq": 2})
            self.assertEqual(res.status_code, 200)
            obj_name = res.get_json()["object"]
            self.assertTrue(obj_name.endswith("_2.dbk2"), f"Expected .dbk2 extension, got: {obj_name}")
            self.assertTrue(obj_name.startswith(f"{self.pc_id}/TestDB/"))

    def test_08_verify_endpoint(self):
        """POST /verify validates token without granting upload."""
        res = self.client.post("/verify", headers=self.auth_header())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json().get("status"), "verified")

        res_bad = self.client.post("/verify", headers=self.auth_header(secret="wrong"))
        self.assertEqual(res_bad.status_code, 401)

    def test_09_customer_mismatch(self):
        """Rejects token if pc_id does not start with CUSTOMER_SLUG-."""
        broker_main.CUSTOMER_SLUG = "acme"
        # Token pc_id is 'pc-cust-01', which does not start with 'acme-'
        res = self.client.post("/verify", headers=self.auth_header())
        self.assertEqual(res.status_code, 401)

        # Token matching customer slug 'acme-pc01'
        acme_pc = "acme-pc01"
        secret_hash = hashlib.sha256(self.secret.encode("utf-8")).hexdigest()
        with open(self.tokens_path, "w", encoding="utf-8") as f:
            json.dump({acme_pc: secret_hash}, f)

        res_ok = self.client.post("/verify", headers=self.auth_header(pc_id=acme_pc))
        self.assertEqual(res_ok.status_code, 200)

    def test_10_strict_db_regex(self):
        """Rejects empty, path traversal, or special characters in database name."""
        # Path traversal
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "../../etc/passwd", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid database name", res.get_json().get("error", ""))

        # Spaces in db name
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "DB With Spaces", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 400)

        # Empty string
        res = self.client.post("/request-upload", headers=self.auth_header(),
                               json={"db": "", "size": 1024, "seq": 1})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
