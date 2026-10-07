"""
Unit Tests: Real vs Mock Endpoint Rejection & dev_broker.py Integration
=============================================================================
Enforces Round 9 Requirements:
1. Release builds reject any mock URL ("-mock-", "mock-uc").
2. No fake OK_MOCKED response ever occurs.
3. Real HTTPS / HTTP calls against dev_broker succeed when live and fail when offline.
"""

import os
import sys
import unittest
import time
import requests

# Add project root to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from preflight import (
    validate_broker_url_security,
    probe_broker_health,
    verify_token_with_broker,
    validate_scheduled_task,
)
from dev_broker import DevBrokerServer


class TestRealVsMockRejection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ALLOW_INSECURE_BROKER"] = "true"
        # Start local dev broker on port 8999 for testing
        cls.port = 8999
        cls.server = DevBrokerServer(port=cls.port)
        cls.server.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        # Wait for server to bind
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        os.environ.pop("ALLOW_INSECURE_BROKER", None)

    def test_mock_url_strictly_rejected(self):
        """[MODE: REAL] Verify that release preflight explicitly rejects mock URLs."""
        mock_urls = [
            "https://broker-acme-mock-uc.a.run.app",
            "https://upload-broker-mock-service.run.app",
            "https://dev-mock-broker.com",
            "https://company-mock-uc.run.app",
        ]
        for url in mock_urls:
            res = validate_broker_url_security(url)
            self.assertFalse(res.passed, f"Mock URL should have been rejected: {url}")
            self.assertIn(res.code, ("ERR_MOCK_URL_FORBIDDEN", "ERR_NOT_APPS_SCRIPT"))

    def test_no_ok_mocked_in_health_probe(self):
        """[MODE: REAL] Verify health probe never short-circuits to OK_MOCKED on mock URLs."""
        res = probe_broker_health("https://broker-acme-mock-uc.a.run.app")
        self.assertFalse(res.passed)
        self.assertNotEqual(res.code, "OK_MOCKED")
        self.assertIn(res.code, ("ERR_MOCK_URL_FORBIDDEN", "ERR_NOT_APPS_SCRIPT", "HTTP_502"))

    def test_no_ok_mocked_in_token_verify(self):
        """[MODE: REAL] Verify token verify never short-circuits to OK_MOCKED."""
        res = verify_token_with_broker("https://broker-acme-mock-uc.a.run.app", "pc-test-01.secret1234567890abcdef12345678")
        self.assertFalse(res.passed)
        self.assertNotEqual(res.code, "OK_MOCKED")

    def test_live_dev_broker_health_succeeds(self):
        """[MODE: REAL] Real HTTP call to live dev_broker returns HTTP 200 OK."""
        res = probe_broker_health(self.base_url)
        self.assertTrue(res.passed)
        self.assertEqual(res.code, "OK")

    def test_offline_broker_fails_real(self):
        """[MODE: REAL] Real HTTP call to offline port fails with network error."""
        res = probe_broker_health("http://127.0.0.1:54321")
        self.assertFalse(res.passed)
        self.assertIn(res.code, ("ERR_BROKER_OFFLINE", "ERR_HTTP_INSECURE", "ERR_CONN_REFUSED", "ERR_HEALTH_EXCEPTION"))

    def test_live_dev_broker_token_verification(self):
        """[MODE: REAL] Real POST /verify against dev_broker validates active token."""
        valid_token = "pc-test-01.secret1234567890abcdef12345678"
        res = verify_token_with_broker(self.base_url, valid_token)
        self.assertTrue(res.passed, f"Verify failed: {res.message}")
        self.assertEqual(res.code, "OK")
        self.assertIn("pc-test-01", res.message)

    def test_invalid_token_rejected_by_real_dev_broker(self):
        """[MODE: REAL] Invalid token returns HTTP 401."""
        invalid_token = "invalid_token_no_dot"
        res = verify_token_with_broker(self.base_url, invalid_token)
        self.assertFalse(res.passed)


if __name__ == "__main__":
    unittest.main()
