"""
Test Suite: Bidirectional DPAPI Interoperability (Python ctypes <-> PowerShell)
=============================================================================
Requirement D: Verifies that native ctypes crypt32.dll DPAPI (Machine Scope 0x4)
interoperates seamlessly with PowerShell [ProtectedData]::Protect / Unprotect
under normal and system accounts.
"""

import os
import sys
import tempfile
import unittest
import subprocess

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from broker_client import _protect_dpapi_native, _unprotect_dpapi_native


class TestDPAPIInterop(unittest.TestCase):

    def test_01_python_protect_powershell_unprotect(self):
        """Encrypt in Python via ctypes crypt32 -> Decrypt in PowerShell."""
        secret_token = "pc-interop-test-01.aB3dE5gH7jK9mN1pQ3sU5wY7"
        encrypted_py = _protect_dpapi_native(secret_token.encode("utf-8"))
        self.assertIsNotNone(encrypted_py)
        self.assertGreater(len(encrypted_py), 100)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp.write(encrypted_py)
            tmp_path = tmp.name

        try:
            ps_script = (
                "Add-Type -AssemblyName System.Security; "
                f"$bytes = [System.IO.File]::ReadAllBytes('{tmp_path}'); "
                "$dec = [System.Security.Cryptography.ProtectedData]::Unprotect("
                "    $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine); "
                "[System.Text.Encoding]::UTF8.GetString($dec)"
            )
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            self.assertEqual(res.returncode, 0, f"PowerShell failed: {res.stderr}")
            self.assertEqual(res.stdout.strip(), secret_token)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_02_powershell_protect_python_unprotect(self):
        """Encrypt in PowerShell via ProtectedData -> Decrypt in Python via ctypes crypt32."""
        secret_token = "pc-powershell-test-02.zX8vT6rP4nL2jH0fD8bA6"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            tmp_path = tmp.name

        try:
            ps_script = (
                "Add-Type -AssemblyName System.Security; "
                f"$bytes = [System.Text.Encoding]::UTF8.GetBytes('{secret_token}'); "
                "$prot = [System.Security.Cryptography.ProtectedData]::Protect("
                "    $bytes, $null, [System.Security.Cryptography.DataProtectionScope]::LocalMachine); "
                f"[System.IO.File]::WriteAllBytes('{tmp_path}', $prot)"
            )
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            self.assertEqual(res.returncode, 0, f"PowerShell failed: {res.stderr}")

            with open(tmp_path, "rb") as f:
                encrypted_ps = f.read()

            decrypted_py = _unprotect_dpapi_native(encrypted_ps)
            self.assertEqual(decrypted_py, secret_token)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
