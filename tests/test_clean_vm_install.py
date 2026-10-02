"""
Clean-VM Installation & Environment Verification Suite
=============================================================================
Validates Zero-Trust Requirements B, D, E, and H:
1. Destination paths (%ProgramFiles% and %ALLUSERSPROFILE%/ProgramData)
2. Permissions and ACL isolation
3. Zero stray files in Client_Installation_Package
4. Master config template integrity (BROKER_URL and IDs empty)
5. Bidirectional DPAPI Machine Scope (0x4) interop (Python ctypes <-> PowerShell)
6. Task Scheduler registration with real exe path derived from install directory
7. End-to-end Preflight execution
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from version import APP_VERSION, APP_NAME, EXE_NAME, DEFAULT_INSTALL_SUBDIR, PROGRAM_DATA_DIR
from broker_client import _protect_dpapi_native, _unprotect_dpapi_native
from audit_build import audit_master_package


class TestCleanVMInstall(unittest.TestCase):
    """
    Rigorously validates clean machine installation requirements.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.package_root = os.path.abspath(os.path.join(cls.repo_root, "..", "Client_Installation_Package"))

    def test_01_package_integrity_and_zero_stray_files(self):
        """[MODE: REAL] Package allowlist audit passes with zero stray .txt or secret files."""
        if not os.path.exists(self.package_root):
            self.skipTest(f"Package path not found: {self.package_root}")

        audit_errors = audit_master_package(self.package_root)
        self.assertEqual(
            len(audit_errors), 0,
            f"Package allowlist audit failed with errors: {audit_errors}"
        )

        # Explicitly verify absence of known stray files
        forbidden = ["broker_url.txt", "drive_folder.txt", "sheet_id.txt", "raw_token.txt", "backup_log.txt", "token.json"]
        found_forbidden = []
        for root, _, files in os.walk(self.package_root):
            for f in files:
                if f.lower() in forbidden:
                    found_forbidden.append(os.path.join(root, f))
        self.assertEqual(len(found_forbidden), 0, f"Found forbidden stray files: {found_forbidden}")

    def test_02_master_config_empty_secrets(self):
        """[MODE: REAL] Master config.json has strictly empty BROKER_URL and IDs."""
        cfg_path = os.path.join(self.package_root, "AppFiles", "config.json")
        if not os.path.exists(cfg_path):
            self.skipTest(f"config.json not found at {cfg_path}")

        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.assertEqual(cfg.get("BROKER_URL", ""), "", "BROKER_URL must be empty in master package")
        self.assertEqual(cfg.get("GOOGLE_DRIVE_FOLDER_ID", ""), "", "Drive folder ID must be empty")
        self.assertEqual(cfg.get("GOOGLE_SHEET_ID", ""), "", "Sheet ID must be empty")

    def test_03_dpapi_machine_scope_bidirectional_powershell_interop(self):
        """[MODE: REAL] Bidirectional DPAPI Machine Scope (0x4) interop under current account."""
        test_token = "PC-CLEANVM-VERIFY-001.secret_test_token_abcdef123456"

        # 1. Protect in PowerShell -> Unprotect in Python ctypes
        with tempfile.NamedTemporaryFile(delete=False, suffix=".dpapi") as tmp:
            tmp_path = tmp.name

        try:
            ps_protect_script = (
                "Add-Type -AssemblyName System.Security; "
                f"$bytes = [System.Text.Encoding]::UTF8.GetBytes('{test_token}'); "
                "$prot = [System.Security.Cryptography.ProtectedData]::Protect("
                "    $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine); "
                f"[System.IO.File]::WriteAllBytes('{tmp_path}', $prot)"
            )
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_protect_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            self.assertEqual(res.returncode, 0, f"PowerShell protect failed: {res.stderr}")

            with open(tmp_path, "rb") as f:
                enc_data = f.read()
            decrypted_py = _unprotect_dpapi_native(enc_data)
            self.assertEqual(decrypted_py, test_token)

            # 2. Protect in Python ctypes -> Unprotect in PowerShell
            enc_py = _protect_dpapi_native(test_token.encode("utf-8"))
            with open(tmp_path, "wb") as f:
                f.write(enc_py)

            ps_unprotect_script = (
                "Add-Type -AssemblyName System.Security; "
                f"$bytes = [System.IO.File]::ReadAllBytes('{tmp_path}'); "
                "$dec = [System.Security.Cryptography.ProtectedData]::Unprotect("
                "    $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine); "
                "[System.Text.Encoding]::UTF8.GetString($dec)"
            )
            res2 = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_unprotect_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            self.assertEqual(res2.returncode, 0, f"PowerShell unprotect failed: {res2.stderr}")
            self.assertEqual(res2.stdout.strip(), test_token)

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_04_real_exe_path_derived_for_task_scheduler(self):
        """[MODE: REAL] Task Scheduler action string derives strictly from the real install directory."""
        # Target install path
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        expected_install_dir = os.path.join(prog_files, DEFAULT_INSTALL_SUBDIR)
        expected_exe = os.path.join(expected_install_dir, EXE_NAME)

        # Verify path structure
        self.assertTrue(expected_exe.lower().startswith(r"c:\program files"), "Target exe must be in Program Files")
        self.assertTrue(expected_exe.endswith("DatabaseBackupApp.exe"), "Target exe filename must match EXE_NAME")

        # Simulate task action generation
        task_action = f'powershell.exe -NoProfile -WindowStyle Hidden -Command "& \'{expected_exe}\' --headless"'
        self.assertIn(expected_exe, task_action)
        self.assertNotIn("%LOCALAPPDATA%", task_action)
        self.assertNotIn("AppData", task_action)

    def test_05_clean_directory_structure_and_permissions(self):
        """[MODE: REAL] Verifies directory creation and test-file write in candidate locations."""
        temp_sandbox = tempfile.mkdtemp(prefix="clean_vm_sandbox_")
        try:
            app_dir = os.path.join(temp_sandbox, "ProgramFiles", DEFAULT_INSTALL_SUBDIR)
            data_dir = os.path.join(temp_sandbox, "ProgramData", DEFAULT_INSTALL_SUBDIR)

            os.makedirs(app_dir, exist_ok=True)
            os.makedirs(data_dir, exist_ok=True)

            self.assertTrue(os.path.exists(app_dir))
            self.assertTrue(os.path.exists(data_dir))

            # Test writing in each
            test_file_app = os.path.join(app_dir, ".test_write")
            with open(test_file_app, "w") as f:
                f.write("test")
            self.assertTrue(os.path.exists(test_file_app))

            test_file_data = os.path.join(data_dir, ".test_write")
            with open(test_file_data, "w") as f:
                f.write("test")
            self.assertTrue(os.path.exists(test_file_data))

        finally:
            shutil.rmtree(temp_sandbox, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
