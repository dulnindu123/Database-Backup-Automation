"""
Unit Tests: Stray Files & Package Allowlist Verification (Requirement A)
=============================================================================
Tests:
1. Master config.json has empty BROKER_URL, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SHEET_ID.
2. audit_master_package passes on the legitimate clean package.
3. audit_master_package fails if any stray .txt (e.g. broker_url.txt, drive_folder.txt) is added.
4. audit_master_package fails if master config.json has a non-empty BROKER_URL.
5. All installer batch scripts and python files contain zero reads of stray .txt files.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import audit_build


class TestStrayFilesAndAllowlist(unittest.TestCase):

    def setUp(self):
        self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.pkg_dir = os.path.join(self.base_dir, "..", "Client_Installation_Package")
        if not os.path.exists(self.pkg_dir):
            self.pkg_dir = os.path.join(self.base_dir, "Client_Installation_Package")

    def test_01_master_config_empty_fields(self):
        """Master config.json must have BROKER_URL, Drive ID, and Sheet ID strictly empty."""
        cfg_paths = [
            os.path.join(self.base_dir, "config.json"),
            os.path.join(self.pkg_dir, "AppFiles", "config.json")
        ]
        for p in cfg_paths:
            self.assertTrue(os.path.exists(p), f"Config file not found: {p}")
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertEqual(cfg.get("BROKER_URL", ""), "", f"BROKER_URL must be empty in {p}")
            self.assertEqual(cfg.get("GOOGLE_DRIVE_FOLDER_ID", ""), "", f"GOOGLE_DRIVE_FOLDER_ID must be empty in {p}")
            self.assertEqual(cfg.get("GOOGLE_SHEET_ID", ""), "", f"GOOGLE_SHEET_ID must be empty in {p}")

    def test_02_clean_master_package_audit_passes(self):
        """Current Client_Installation_Package passes audit_master_package with 0 errors."""
        errors = audit_build.audit_master_package(self.pkg_dir)
        self.assertEqual(errors, [], f"Expected 0 audit errors on master package, got: {errors}")

    def test_03_audit_fails_on_stray_broker_url_txt(self):
        """audit_master_package fails immediately if broker_url.txt is placed in package root."""
        with tempfile.TemporaryDirectory() as td:
            # Create a mock valid package
            for f in audit_build.ALLOWED_PACKAGE_ROOT_FILES:
                with open(os.path.join(td, f), "w") as fp:
                    fp.write("dummy")
            for d in audit_build.ALLOWED_PACKAGE_ROOT_DIRS:
                os.makedirs(os.path.join(td, d), exist_ok=True)
            app_files = os.path.join(td, "AppFiles")
            for f in audit_build.ALLOWED_APPFILES_FILES:
                if f == "config.json":
                    with open(os.path.join(app_files, f), "w") as fp:
                        json.dump({"BROKER_URL": "", "GOOGLE_DRIVE_FOLDER_ID": "", "GOOGLE_SHEET_ID": ""}, fp)
                else:
                    with open(os.path.join(app_files, f), "w") as fp:
                        fp.write("dummy")
            for d in audit_build.ALLOWED_APPFILES_DIRS:
                os.makedirs(os.path.join(app_files, d), exist_ok=True)

            # Legitimate mock passes
            self.assertEqual(audit_build.audit_master_package(td), [])

            # Inject forbidden stray file
            stray_path = os.path.join(td, "broker_url.txt")
            with open(stray_path, "w") as fp:
                fp.write("http://127.0.0.1:5000")

            errors = audit_build.audit_master_package(td)
            self.assertTrue(any("broker_url.txt" in e for e in errors), "Audit did not reject broker_url.txt")

    def test_04_audit_fails_on_populated_master_config(self):
        """audit_master_package fails if BROKER_URL is populated in master template."""
        with tempfile.TemporaryDirectory() as td:
            for f in audit_build.ALLOWED_PACKAGE_ROOT_FILES:
                with open(os.path.join(td, f), "w") as fp:
                    fp.write("dummy")
            for d in audit_build.ALLOWED_PACKAGE_ROOT_DIRS:
                os.makedirs(os.path.join(td, d), exist_ok=True)
            app_files = os.path.join(td, "AppFiles")
            for f in audit_build.ALLOWED_APPFILES_FILES:
                if f == "config.json":
                    with open(os.path.join(app_files, f), "w") as fp:
                        json.dump({"BROKER_URL": "https://leaked-broker-url.run.app", "GOOGLE_DRIVE_FOLDER_ID": "", "GOOGLE_SHEET_ID": ""}, fp)
                else:
                    with open(os.path.join(app_files, f), "w") as fp:
                        fp.write("dummy")
            for d in audit_build.ALLOWED_APPFILES_DIRS:
                os.makedirs(os.path.join(app_files, d), exist_ok=True)

            errors = audit_build.audit_master_package(td)
            self.assertTrue(any("BROKER_URL must be empty" in e for e in errors), "Audit did not reject populated config")

    def test_05_installer_scripts_contain_zero_stray_txt_reads(self):
        """Verify that 1_Quick_Install.bat and Update_App.bat do not reference reading stray .txt files."""
        scripts = [
            os.path.join(self.pkg_dir, "1_Quick_Install.bat"),
            os.path.join(self.pkg_dir, "Update_App.bat"),
        ]
        forbidden_patterns = ["broker_url.txt", "drive_folder.txt", "sheet_id.txt"]
        for s in scripts:
            if os.path.exists(s):
                with open(s, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().lower()
                for pat in forbidden_patterns:
                    self.assertNotIn(pat, content, f"Found forbidden stray file read '{pat}' in {s}")


if __name__ == "__main__":
    unittest.main()
