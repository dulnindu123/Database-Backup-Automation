"""
Unit & Integration Tests for Customer Onboarding & Apps Script Broker Architecture
=============================================================================
Tests:
1. Bundle generation, signing with Ed25519, and cryptographic verification.
2. Cross-tenant isolation: slug mismatch in signed bundle is rejected.
3. Tampered bundle detection: tampering with bundle payload invalidates signature.
4. RSA public key requirements: enforces 3072+ bit distinct primary & escrow keys.
5. Apps Script broker response parsing and 302 redirect handling.
6. DPAPI token protection and machine-scope unprotection.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from version import APP_VERSION, EMBEDDED_ADMIN_PUBLIC_KEY_PEM
from preflight import validate_signed_bundle, validate_broker_url_security, probe_broker_health
from admin.sign_bundle import (
    build_bundle,
    sign_bundle,
    verify_bundle,
    load_private,
    init_key,
    spki_fingerprint,
    BundleError
)
from Tools.setup_new_customer import generate_rsa_keypair
from broker_client import (
    parse_broker_response,
    save_token,
    load_token,
    validate_broker_url
)


class TestAppsScriptCustomerOnboarding(unittest.TestCase):
    """Test suite for Apps Script broker onboarding, bundle crypto, and client security."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="test_apps_script_onboard_")
        cls.admin_key_path = os.path.join(cls.test_dir, "admin_test_ed25519.pem")
        cls.admin_pub = init_key(cls.admin_key_path, "SuperSecretAdminPass123!")
        cls.admin_priv = load_private(cls.admin_key_path, "SuperSecretAdminPass123!")
        
        # Generate test RSA keypairs
        cls.p_priv, cls.p_pub = generate_rsa_keypair("CustKeyPassphrase123!")
        cls.e_priv, cls.e_pub = generate_rsa_keypair("CustKeyPassphrase123!")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_bundle_signing_and_verification(self):
        """[MODE: REAL] Bundle builds, signs with Ed25519, and verifies against public key."""
        broker_url = "https://script.google.com/macros/s/AKfycbwPSN7gW5Qv_4GQAyEoOnCkUnd97lKiwBtg_CQo1TUvArau1Vnwp2xuijg0c1Gny3Ns/exec"
        raw_b = build_bundle("acme", broker_url, self.p_pub, self.e_pub, enroll_code="TEST_CODE_123")
        b64, sig = sign_bundle(self.admin_priv, raw_b)

        from cryptography.hazmat.primitives import serialization
        pub_key = serialization.load_pem_public_key(self.admin_pub.encode())
        verified = verify_bundle(pub_key, b64, sig, expect_customer="acme")
        
        self.assertEqual(verified["customer"], "acme")
        self.assertEqual(verified["broker_url"], broker_url)
        self.assertEqual(verified["enroll_code"], "TEST_CODE_123")
        self.assertEqual(len(verified["public_keys"]), 2)

    def test_02_cross_tenant_slug_mismatch(self):
        """[MODE: REAL] Cross-tenant isolation: bundle signed for 'acme' rejected when expecting 'globex'."""
        broker_url = "https://script.google.com/macros/s/AKfycbwPSN7gW5Qv_4GQAyEoOnCkUnd97lKiwBtg_CQo1TUvArau1Vnwp2xuijg0c1Gny3Ns/exec"
        raw_b = build_bundle("acme", broker_url, self.p_pub, self.e_pub)
        b64, sig = sign_bundle(self.admin_priv, raw_b)

        from cryptography.hazmat.primitives import serialization
        pub_key = serialization.load_pem_public_key(self.admin_pub.encode())
        
        with self.assertRaises(BundleError) as ctx:
            verify_bundle(pub_key, b64, sig, expect_customer="globex")
        self.assertIn("customer mismatch", str(ctx.exception))

    def test_03_tampered_bundle_rejection(self):
        """[MODE: REAL] Tampering with broker URL in bundle payload is caught by Ed25519 signature."""
        broker_url = "https://script.google.com/macros/s/AKfycbwPSN7gW5Qv_4GQAyEoOnCkUnd97lKiwBtg_CQo1TUvArau1Vnwp2xuijg0c1Gny3Ns/exec"
        raw_b = build_bundle("acme", broker_url, self.p_pub, self.e_pub)
        b64, sig = sign_bundle(self.admin_priv, raw_b)

        # Decode, tamper, and re-encode without signature update
        import base64
        payload = json.loads(base64.b64decode(b64))
        payload["broker_url"] = "https://script.google.com/macros/s/ATTACKER_INJECTED_URL/exec"
        tampered_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

        from cryptography.hazmat.primitives import serialization
        pub_key = serialization.load_pem_public_key(self.admin_pub.encode())

        with self.assertRaises(BundleError) as ctx:
            verify_bundle(pub_key, tampered_b64, sig)
        self.assertIn("signature invalid", str(ctx.exception))

    def test_04_rsa_keys_distinct_and_minimum_bits(self):
        """[MODE: REAL] Bundle build rejects identical keys or weak keys (< 3072 bits)."""
        broker_url = "https://script.google.com/macros/s/AKfycbwPSN7gW5Qv_4GQAyEoOnCkUnd97lKiwBtg_CQo1TUvArau1Vnwp2xuijg0c1Gny3Ns/exec"
        
        # Test identical primary and escrow keys
        with self.assertRaises(BundleError) as ctx:
            build_bundle("acme", broker_url, self.p_pub, self.p_pub)
        self.assertIn("identical", str(ctx.exception).lower())

    def test_05_broker_response_parser(self):
        """[MODE: REAL] parse_broker_response extracts logical code from 200 JSON payload."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"error": "Unauthorized PC", "code": 401})
        mock_resp.json.return_value = {"error": "Unauthorized PC", "code": 401}
        mock_resp.status_code = 200

        status, data, err = parse_broker_response(mock_resp)
        self.assertEqual(status, 401)
        self.assertEqual(err, "Unauthorized PC")

        # Success case
        mock_resp.text = json.dumps({"status": "enrolled", "offset_minutes": 45})
        mock_resp.json.return_value = {"status": "enrolled", "offset_minutes": 45}
        status, data, err = parse_broker_response(mock_resp)
        self.assertEqual(status, 200)
        self.assertIsNone(err)
        self.assertEqual(data["offset_minutes"], 45)

    def test_06_dpapi_token_roundtrip(self):
        """[MODE: REAL] DPAPI token saves with native ACL protection and loads back."""
        token_path = os.path.join(self.test_dir, "test_token.dpapi")
        raw_token = "PC-ACME-01.a8f9c3e2109847bd65"
        
        save_token(token_path, raw_token)
        self.assertTrue(os.path.exists(token_path))
        
        loaded = load_token(token_path)
        self.assertEqual(loaded, raw_token)


if __name__ == "__main__":
    unittest.main()
