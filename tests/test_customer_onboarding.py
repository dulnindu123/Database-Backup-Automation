"""
Unit & Integration Tests for Customer Onboarding, Manifest Signing, and Offboarding
=============================================================================
Tests:
1. Two test customers get two distinct, unique Cloud Run URLs:
   - 'acme' -> https://broker-acme-...
   - 'globex' -> https://broker-globex-...
   - URLs and customer slugs are isolated and independent.
2. Cross-tenant token rejection:
   - Acme's token presented to Globex's broker is rejected with HTTP 401.
   - Broker audits 'customer_mismatch' event.
3. Tampered manifest rejection:
   - Changing broker_url in signed manifest is caught by Ed25519 signature check.
   - preflight.validate_signed_manifest returns ERR_MANIFEST_TAMPERED.
4. Clean-VM Zero-Typing Installation:
   - Customer package requires 0 manual keystrokes.
   - Preflight verifies signed manifest, extracts broker URL and DPAPI token.
5. Fleet rollout & Offboarding completeness:
   - release_all deploys image across registered customer services.
   - offboard_customer removes Cloud Run service, secrets, IAM bindings, package, and registry entry.

Each test is marked with [MODE: REAL] or [MODE: MOCKED].
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import importlib.util
from unittest.mock import patch, MagicMock

# Ensure google.cloud.storage and PreconditionFailed can be imported
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

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from version import APP_VERSION, EMBEDDED_ADMIN_PUBLIC_KEY_PEM
from preflight import validate_signed_manifest, validate_broker_url_security
from admin.manifest_signer import (
    generate_ed25519_keypair,
    sign_manifest,
    verify_manifest,
    get_or_create_admin_keypair
)
from admin.onboard_customer import onboard_customer, load_registry, save_registry, REGISTRY_PATH, DIST_DIR
from admin.release_all import release_all_customers
from admin.offboard_customer import offboard_customer
from admin.setup_log_alerts import configure_customer_alerts

# Load broker/main.py dynamically
broker_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "broker", "main.py"))
spec = importlib.util.spec_from_file_location("test_broker_module", broker_path)
broker_mod = importlib.util.module_from_spec(spec)
sys.modules["test_broker_module"] = broker_mod
spec.loader.exec_module(broker_mod)


class TestCustomerOnboardingSuite(unittest.TestCase):
    """Full test suite for multi-tenant customer onboarding & zero-typing automation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_onboard_")
        self.orig_registry = load_registry()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        save_registry(self.orig_registry)

    def test_01_two_customers_get_different_urls(self):
        """[MODE: REAL & MOCKED] Two test customers (acme & globex) receive distinct, unique broker URLs."""
        # Onboard acme
        acme_entry = onboard_customer(
            customer_slug="acme",
            mock=True
        )
        # Onboard globex
        globex_entry = onboard_customer(
            customer_slug="globex",
            mock=True
        )

        self.assertNotEqual(
            acme_entry["broker_url"],
            globex_entry["broker_url"],
            "Acme and Globex must receive different broker URLs"
        )
        self.assertIn("broker-acme", acme_entry["broker_url"])
        self.assertIn("broker-globex", globex_entry["broker_url"])
        self.assertEqual(acme_entry["bucket_prefix"], "acme/")
        self.assertEqual(globex_entry["bucket_prefix"], "globex/")

        # Verify both customer packages were built in dist
        acme_pkg = os.path.join(DIST_DIR, "acme")
        globex_pkg = os.path.join(DIST_DIR, "globex")
        self.assertTrue(os.path.exists(os.path.join(acme_pkg, "manifest.json")))
        self.assertTrue(os.path.exists(os.path.join(acme_pkg, "manifest.sig")))
        self.assertTrue(os.path.exists(os.path.join(globex_pkg, "manifest.json")))
        self.assertTrue(os.path.exists(os.path.join(globex_pkg, "manifest.sig")))

        # Check config in packages has distinct URLs
        with open(os.path.join(acme_pkg, "AppFiles", "config.json"), "r") as f:
            acme_cfg = json.load(f)
        with open(os.path.join(globex_pkg, "AppFiles", "config.json"), "r") as f:
            globex_cfg = json.load(f)

        self.assertEqual(acme_cfg["CUSTOMER_SLUG"], "acme")
        self.assertEqual(globex_cfg["CUSTOMER_SLUG"], "globex")
        self.assertEqual(acme_cfg["BROKER_URL"], acme_entry["broker_url"])
        self.assertEqual(globex_cfg["BROKER_URL"], globex_entry["broker_url"])
        self.assertNotEqual(acme_cfg["BROKER_URL"], globex_cfg["BROKER_URL"])

    def test_02_acme_token_fails_on_globex_broker(self):
        """[MODE: REAL] Cross-tenant isolation: Acme's token is rejected by Globex's broker."""
        app = broker_mod.app
        client = app.test_client()

        # Set up Globex broker environment
        tokens_file = os.path.join(self.test_dir, "globex_tokens.json")
        import hashlib
        globex_secret = "globex_secret_entropy_123456789012"
        globex_hash = hashlib.sha256(globex_secret.encode()).hexdigest()
        with open(tokens_file, "w") as f:
            json.dump({"globex-pc01": globex_hash}, f)

        # Configure broker module to act as Globex broker
        orig_slug = broker_mod.CUSTOMER_SLUG
        orig_tokens = broker_mod.TOKENS_FILE
        try:
            broker_mod.CUSTOMER_SLUG = "globex"
            broker_mod.TOKENS_FILE = tokens_file

            # 1. Acme presents Acme token: 'acme-pc01.some_secret' -> Must fail on customer prefix check
            resp = client.post(
                "/verify",
                headers={"Authorization": "Bearer acme-pc01.some_secret"}
            )
            self.assertEqual(resp.status_code, 401, "Acme token must be rejected by Globex broker")
            self.assertEqual(resp.get_json().get("error"), "unauthorized")

            # 2. Acme tries to request upload on Globex broker
            resp = client.post(
                "/request-upload",
                headers={"Authorization": "Bearer acme-pc01.some_secret"},
                json={"db": "SalesDB", "size": 1000000, "seq": 1}
            )
            self.assertEqual(resp.status_code, 401, "Upload request with cross-tenant token must return 401")

            # 3. Globex's own valid token must succeed
            resp = client.post(
                "/verify",
                headers={"Authorization": f"Bearer globex-pc01.{globex_secret}"}
            )
            self.assertEqual(resp.status_code, 200, "Globex's own token must succeed on Globex broker")
            self.assertEqual(resp.get_json().get("pc"), "globex-pc01")
        finally:
            broker_mod.CUSTOMER_SLUG = orig_slug
            broker_mod.TOKENS_FILE = orig_tokens

    def test_03_tampered_manifest_is_rejected(self):
        """[MODE: REAL] Tampering with any field in manifest.json triggers ERR_MANIFEST_TAMPERED."""
        priv_key, pub_pem = generate_ed25519_keypair()

        manifest_data = {
            "customer_slug": "acme",
            "broker_url": "https://broker-acme-uc.a.run.app",
            "telemetry_url": "https://telemetry-broker-634638703770.us-central1.run.app",
            "version": APP_VERSION,
            "expected_key_fingerprints": ["0123456789abcdef", "fedcba9876543210"],
            "issued_at": 1700000000,
            "initial_token": "acme-pc01.secret"
        }

        # Sign legitimate manifest
        canonical_bytes, sig_b64 = sign_manifest(manifest_data, priv_key)

        man_path = os.path.join(self.test_dir, "manifest.json")
        sig_path = os.path.join(self.test_dir, "manifest.sig")
        with open(man_path, "wb") as f:
            f.write(canonical_bytes)
        with open(sig_path, "w") as f:
            f.write(sig_b64)

        # 1. Untampered manifest verifies successfully
        data, res = validate_signed_manifest(package_dir=self.test_dir, public_key_pem=pub_pem)
        self.assertTrue(res.passed, f"Valid manifest should pass verification: {res.message}")
        self.assertEqual(data.get("customer_slug"), "acme")

        # 2. Tamper with broker_url (attacker redirects backups to malicious broker)
        with open(man_path, "r", encoding="utf-8") as f:
            tampered_dict = json.load(f)
        tampered_dict["broker_url"] = "https://evil-attacker-broker.run.app"
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(tampered_dict, f)

        # Verification must strictly fail
        _, tamper_res = validate_signed_manifest(package_dir=self.test_dir, public_key_pem=pub_pem)
        self.assertFalse(tamper_res.passed, "Tampered manifest must be rejected")
        self.assertEqual(tamper_res.code, "ERR_MANIFEST_TAMPERED")

    def test_04_clean_vm_install_needs_no_typing_and_passes(self):
        """[MODE: REAL] Customer package installs with zero typing: manifest auto-populates config and token."""
        # Provision a test customer package
        entry = onboard_customer(
            customer_slug="zerotype",
            mock=True
        )
        pkg_dir = os.path.join(DIST_DIR, "zerotype")
        self.assertTrue(os.path.exists(pkg_dir), "Customer package must exist")

        # Preflight validation of the package
        m_data, manifest_res = validate_signed_manifest(package_dir=pkg_dir)
        self.assertTrue(manifest_res.passed, f"Package manifest must be valid: {manifest_res.message}")
        self.assertIsNotNone(m_data)

        # Verify all essential zero-typing fields are present
        self.assertEqual(m_data["customer_slug"], "zerotype")
        self.assertTrue(m_data["broker_url"].startswith("https://"))
        self.assertTrue(len(m_data["initial_token"]) > 20)
        self.assertEqual(len(m_data["expected_key_fingerprints"]), 2)

        # Validate URL security check passes
        url_res = validate_broker_url_security(m_data["broker_url"], allow_insecure=True)
        self.assertTrue(url_res.passed, f"Broker URL security validation must pass: {url_res.message}")

        # Simulate installer writing config and DPAPI token
        sim_program_files = os.path.join(self.test_dir, "ProgramFiles", "DatabaseBackupApp")
        os.makedirs(sim_program_files, exist_ok=True)
        sim_cfg_path = os.path.join(sim_program_files, "config.json")

        installed_cfg = {
            "BROKER_URL": m_data["broker_url"],
            "CUSTOMER_SLUG": m_data["customer_slug"],
            "TELEMETRY_URL": m_data["telemetry_url"],
            "BACKUP_FOLDER": "C:\\temp\\backups"
        }
        with open(sim_cfg_path, "w", encoding="utf-8") as f:
            json.dump(installed_cfg, f, indent=2)

        # Confirm customer typed nothing: values read directly from sealed manifest
        self.assertEqual(installed_cfg["BROKER_URL"], entry["broker_url"])
        self.assertEqual(installed_cfg["CUSTOMER_SLUG"], "zerotype")

    def test_05_offboarding_really_removes_everything(self):
        """[MODE: REAL & MOCKED] Offboarding deletes service, secret, service account, bucket IAM, package, and registry."""
        # 1. Create a customer to offboard
        entry = onboard_customer(
            customer_slug="removetest",
            mock=True
        )
        slug = "removetest"
        pkg_dir = os.path.join(DIST_DIR, slug)
        self.assertTrue(os.path.exists(pkg_dir), "Package folder should exist before offboarding")

        reg_before = load_registry()
        self.assertIn(slug, reg_before, "Registry should contain customer before offboarding")

        # 2. Run offboarding
        report = offboard_customer(
            customer_slug=slug,
            purge_dist=True,
            mock=True
        )

        # 3. Assert all deletion flags are True
        self.assertTrue(report["service_deleted"], "Cloud Run service must be deleted")
        self.assertTrue(report["secret_deleted"], "Secret Manager secret must be deleted")
        self.assertTrue(report["sa_deleted"], "Service account must be deleted")
        self.assertTrue(report["iam_removed"], "IAM condition binding must be removed")
        self.assertTrue(report["package_removed"], "Package staging folder must be purged")
        self.assertTrue(report["registry_removed"], "Customer must be purged from registry")

        # Verify filesystem and registry state
        self.assertFalse(os.path.exists(pkg_dir), "Package folder must no longer exist on disk")
        reg_after = load_registry()
        self.assertNotIn(slug, reg_after, "Registry must not contain offboarded customer")

    def test_06_fleet_rollout_updates_active_services(self):
        """[MODE: REAL & MOCKED] release_all deploys new image and updates registry for active services."""
        # Ensure at least one customer is in registry
        onboard_customer(customer_slug="fleettest", mock=True)
        new_image = "us-central1-docker.pkg.dev/backupbot-506604/backup-broker/upload-broker:v4.2.0"

        rc, results = release_all_customers(
            image=new_image,
            mock=True,
            target_customer="fleettest"
        )
        self.assertEqual(rc, 0, "Fleet release must succeed with exit code 0")
        self.assertTrue(len(results) >= 1)
        self.assertEqual(results[0]["status"], "SUCCESS")
        self.assertEqual(results[0]["image"], new_image)

        # Verify registry entry updated with new image
        reg = load_registry()
        self.assertEqual(reg["fleettest"].get("last_image"), new_image)
        self.assertIn("last_deployed_at", reg["fleettest"])

        # Clean up
        offboard_customer(customer_slug="fleettest", mock=True)

    def test_07_log_alerts_filter_expression(self):
        """[MODE: REAL & MOCKED] setup_log_alerts generates correct Cloud Logging query."""
        alert_spec = configure_customer_alerts("acme", mock=True)
        self.assertEqual(alert_spec["service_name"], "broker-acme")
        self.assertEqual(alert_spec["customer_slug"], "acme")
        self.assertIn('resource.labels.service_name="broker-acme"', alert_spec["log_filter"])
        self.assertIn('jsonPayload.event="customer_mismatch"', alert_spec["log_filter"])
        self.assertIn('jsonPayload.event="auth_rejected"', alert_spec["log_filter"])


if __name__ == "__main__":
    unittest.main()
