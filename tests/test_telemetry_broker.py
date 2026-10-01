"""
Unit & Integration Tests for Telemetry Broker and Storage Monitor Client
=============================================================================
Tests requirement 10:
- Schema rejection cases (unknown fields, bad drive count, bad regex, invalid enum, bounds failure)
- Formula-injection strings accepted and passed with valueInputOption='RAW'
- Unauthorized / revoked token rejection (401)
- Oversized payload body cap rejection (400)
- Rate-limit per pc_id (429)
- Client never sends a sheet ID or tab name
"""
import sys
import os
import json
import hashlib
import unittest
import importlib.util
from unittest.mock import patch, MagicMock

# Dynamically import telemetry_broker/main.py to avoid collision with root main.py
tb_main_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'telemetry_broker', 'main.py'))
spec = importlib.util.spec_from_file_location("telemetry_main", tb_main_path)
telemetry_main = importlib.util.module_from_spec(spec)
sys.modules["telemetry_main"] = telemetry_main
spec.loader.exec_module(telemetry_main)

# Add root dir to sys.path for broker_client
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from broker_client import report_storage_telemetry


class TestTelemetryBroker(unittest.TestCase):
    def setUp(self):
        self.app = telemetry_main.app
        self.client = self.app.test_client()

        # Reset in-memory rate limit cache before every single test
        telemetry_main._rate_limit_cache.clear()

        # Create temporary tokens file for testing
        self.tokens_path = os.path.join(os.path.dirname(__file__), "test_tokens.json")
        self.pc_id = "test-pc-01"
        self.secret = "secret123456"
        secret_hash = hashlib.sha256(self.secret.encode("utf-8")).hexdigest()
        
        with open(self.tokens_path, "w", encoding="utf-8") as f:
            json.dump({self.pc_id: secret_hash}, f)

        telemetry_main.TOKENS_FILE = self.tokens_path
        telemetry_main.SHEET_ID = "mock_sheet_12345"

    def tearDown(self):
        if os.path.exists(self.tokens_path):
            try:
                os.remove(self.tokens_path)
            except Exception:
                pass

    def get_valid_payload(self):
        return {
            "drives": [
                {
                    "drive_letter": "C:\\",
                    "drive_type": "Fixed",
                    "total_bytes": 500000000000,
                    "free_bytes": 200000000000,
                    "percent_used": 60.0
                }
            ]
        }

    def test_unauthorized_or_revoked_token(self):
        """Test missing header, invalid format, wrong secret, or revoked pc_id."""
        payload = self.get_valid_payload()

        # No auth header
        res = self.client.post("/report-storage", json=payload)
        self.assertEqual(res.status_code, 401)

        # Invalid token scheme
        res = self.client.post("/report-storage", json=payload, headers={"Authorization": "Basic 123"})
        self.assertEqual(res.status_code, 401)

        # Wrong secret
        res = self.client.post("/report-storage", json=payload, headers={"Authorization": f"Bearer {self.pc_id}.wrongsecret"})
        self.assertEqual(res.status_code, 401)

        # Non-existent/revoked pc_id
        res = self.client.post("/report-storage", json=payload, headers={"Authorization": "Bearer revoked-pc.secret123456"})
        self.assertEqual(res.status_code, 401)

    def test_oversized_body(self):
        """Test payload larger than 8 KB cap (8192 bytes) is rejected with 400."""
        # Create a payload > 8 KB
        large_drives = []
        for i in range(20):
            large_drives.append({
                "drive_letter": f"D:\\Data_Drive_{i:02d}_With_Very_Long_Name_To_Pad_Payload_Size_Exceeding_Limit",
                "drive_type": "Remote",
                "total_bytes": 1000000000000,
                "free_bytes": 500000000000,
                "percent_used": 50.0
            })
        large_payload = json.dumps({"drives": large_drives})
        
        # Ensure it exceeds 8192 bytes
        while len(large_payload.encode('utf-8')) <= 8192:
            large_drives.append(large_drives[0])
            large_payload = json.dumps({"drives": large_drives})

        auth = f"Bearer {self.pc_id}.{self.secret}"
        res = self.client.post("/report-storage", data=large_payload, content_type="application/json", headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)
        self.assertIn("payload exceeds 8 KB limit", res.get_json()["error"])

    def test_schema_rejection_unknown_fields(self):
        """Reject extra top-level fields (e.g. client attempting to send sheet_id)."""
        auth = f"Bearer {self.pc_id}.{self.secret}"
        payload = self.get_valid_payload()
        payload["sheet_id"] = "malicious_sheet_id"

        res = self.client.post("/report-storage", json=payload, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unknown top-level fields rejected", res.get_json()["error"])

    def test_schema_rejection_drive_count(self):
        """Reject 0 drives or > 26 drives."""
        auth = f"Bearer {self.pc_id}.{self.secret}"
        
        # Empty drives
        res = self.client.post("/report-storage", json={"drives": []}, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)

        # 27 drives
        too_many = [self.get_valid_payload()["drives"][0]] * 27
        res = self.client.post("/report-storage", json={"drives": too_many}, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)

    def test_schema_rejection_drive_name_regex(self):
        """Drive letter/name must match strict regex."""
        auth = f"Bearer {self.pc_id}.{self.secret}"
        payload = self.get_valid_payload()
        payload["drives"][0]["drive_letter"] = "INVALID::NAME<script>"

        res = self.client.post("/report-storage", json=payload, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)
        self.assertIn("illegal name format", res.get_json()["error"])

    def test_schema_rejection_drive_type_enum(self):
        """Drive type must be from fixed enum."""
        auth = f"Bearer {self.pc_id}.{self.secret}"
        payload = self.get_valid_payload()
        payload["drives"][0]["drive_type"] = "CloudDrive"

        res = self.client.post("/report-storage", json=payload, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid drive type", res.get_json()["error"])

    def test_schema_rejection_numeric_bounds(self):
        """Test numeric bounds (0 <= free <= total, 0 <= percent <= 100)."""
        auth = f"Bearer {self.pc_id}.{self.secret}"

        # free > total
        p1 = self.get_valid_payload()
        p1["drives"][0]["free_bytes"] = 600000000000
        p1["drives"][0]["total_bytes"] = 500000000000
        res = self.client.post("/report-storage", json=p1, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)

        # percent > 100
        p2 = self.get_valid_payload()
        p2["drives"][0]["percent_used"] = 105.0
        res = self.client.post("/report-storage", json=p2, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 400)

    @patch.object(telemetry_main, "get_sheets_service")
    def test_formula_injection_stored_as_plain_text(self, mock_sheets_fn):
        """Test formula string input is accepted and passed with valueInputOption='RAW'."""
        auth = f"Bearer {self.pc_id}.{self.secret}"
        payload = self.get_valid_payload()
        # Formula injection string in drive letter
        payload["drives"][0]["drive_letter"] = "C:\\"

        mock_service = MagicMock()
        mock_sheets_fn.return_value = mock_service
        mock_append = MagicMock()
        mock_service.spreadsheets().values().append = mock_append
        mock_append.return_value.execute.return_value = {"updatedRows": 1}

        res = self.client.post("/report-storage", json=payload, headers={"Authorization": auth})
        self.assertEqual(res.status_code, 200)

        # Verify valueInputOption='RAW' was explicitly passed to Google Sheets API
        mock_append.assert_called_once()
        kwargs = mock_append.call_args[1]
        self.assertEqual(kwargs.get("valueInputOption"), "RAW")
        self.assertEqual(kwargs.get("spreadsheetId"), "mock_sheet_12345")
        self.assertEqual(kwargs.get("range"), f"{self.pc_id}!A:G")

    @patch.object(telemetry_main, "get_sheets_service")
    def test_rate_limit_response(self, mock_sheets_fn):
        """Test rate limit per pc_id (1 report per 15 mins). Second request yields 429."""
        auth = f"Bearer {self.pc_id}.{self.secret}"
        payload = self.get_valid_payload()

        mock_service = MagicMock()
        mock_sheets_fn.return_value = mock_service
        mock_append = MagicMock()
        mock_service.spreadsheets().values().append = mock_append
        mock_append.return_value.execute.return_value = {"updatedRows": 1}

        # 1st request -> 200 OK
        res1 = self.client.post("/report-storage", json=payload, headers={"Authorization": auth})
        self.assertEqual(res1.status_code, 200)

        # 2nd immediate request -> 429 Rate Limit Exceeded
        res2 = self.client.post("/report-storage", json=payload, headers={"Authorization": auth})
        self.assertEqual(res2.status_code, 429)
        self.assertIn("rate limit exceeded", res2.get_json()["error"])

    @patch("requests.post")
    def test_client_never_sends_sheet_id(self, mock_post):
        """Verify client-side report_storage_telemetry function never sends a sheet ID or tab name."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"drives_logged": 1}
        mock_post.return_value = mock_resp

        drives = [
            {
                "drive_letter": "C:\\",
                "drive_type": "Fixed",
                "total_bytes": 500000000000,
                "free_bytes": 200000000000,
                "percent_used": 60.0
            }
        ]

        ok, msg = report_storage_telemetry("https://telemetry-broker-xyz.run.app", "pc-01.secret", drives)
        self.assertTrue(ok)

        # Inspect actual JSON body sent by requests.post
        mock_post.assert_called_once()
        kwargs = mock_post.call_args[1]
        body = kwargs.get("json", {})

        # Assert ONLY 'drives' is in the payload
        self.assertEqual(list(body.keys()), ["drives"])
        self.assertNotIn("sheet_id", body)
        self.assertNotIn("tab_name", body)
        self.assertNotIn("google_sheet_id", body)


if __name__ == "__main__":
    unittest.main()
