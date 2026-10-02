"""
Unit Test: Task Scheduler Registration & Exact Verification
=============================================================================
Enforces Round 9 Requirement 3:
- Single constant for task name
- Exact-name check plus program path plus run-as account (no candidate lists)
- Registers a real task on Windows and verifies it.
"""

import os
import sys
import unittest
import subprocess

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from preflight import validate_scheduled_task
from version import DEFAULT_TASK_NAME


class TestTaskSchedulerExact(unittest.TestCase):
    TEST_TASK_NAME = "Test_Database_Cloud_Backup_Exact"
    TEST_EXE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")

    def tearDown(self):
        # Always clean up test task
        subprocess.run(["schtasks.exe", "/delete", "/tn", self.TEST_TASK_NAME, "/f"],
                       capture_output=True, text=True)

    def test_task_not_registered(self):
        """[MODE: REAL] Querying non-existent task returns ERR_TASK_NOT_REGISTERED."""
        res = validate_scheduled_task(task_name=self.TEST_TASK_NAME)
        self.assertFalse(res.passed)
        self.assertEqual(res.code, "ERR_TASK_NOT_REGISTERED")

    def test_register_and_exact_verify_real(self):
        """[MODE: REAL] Registers a real task on Windows and verifies name, path, and run-as account."""
        # 1. Create real task
        tr_cmd = f'"{self.TEST_EXE}" /c echo test'
        create_cmd = [
            "schtasks.exe", "/create",
            "/tn", self.TEST_TASK_NAME,
            "/tr", tr_cmd,
            "/sc", "weekly",
            "/d", "MON",
            "/st", "02:00",
            "/f"
        ]
        res_create = subprocess.run(create_cmd, capture_output=True, text=True)
        if res_create.returncode != 0:
            self.skipTest(f"Insufficient privileges to create scheduled task on this environment: {res_create.stderr}")

        # 2. Verify with matching expected_exe
        res = validate_scheduled_task(task_name=self.TEST_TASK_NAME, expected_exe=self.TEST_EXE)
        self.assertTrue(res.passed, f"Validation failed: {res.message}")
        self.assertEqual(res.code, "OK")
        self.assertIn(self.TEST_TASK_NAME, res.message)
        self.assertIn("Run As", res.message)

        # 3. Verify mismatch detection
        wrong_exe = r"C:\NonExistent\FakeBackup.exe"
        res_mismatch = validate_scheduled_task(task_name=self.TEST_TASK_NAME, expected_exe=wrong_exe)
        self.assertFalse(res_mismatch.passed)
        self.assertEqual(res_mismatch.code, "ERR_TASK_EXE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
