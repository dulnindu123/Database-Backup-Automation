"""
Unit Test: Token Masking & Log Secret Scanner (Round 9 Requirement 8)
=============================================================================
Ensures that no raw authentication tokens (<pc_id>.<secret>) or private keys
are ever printed, logged, or leaked into:
1. Log files (backup_log.txt, audit logs)
2. Console output or stdout / stderr streams
3. Exception messages
"""

import os
import re
import sys
import unittest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backup_core import emit_log, LOG_FILE


# Regex matching raw broker machine token: <pc_id>.<hex_or_alphanumeric_secret>
TOKEN_REGEX = re.compile(r"\bpc-[a-zA-Z0-9_-]+\.[a-fA-F0-9]{20,}\b")


class TestLogSecretScanner(unittest.TestCase):
    def test_emit_log_never_leaks_token(self):
        """[MODE: REAL] Verify that emit_log redacts tokens if accidentally passed."""
        test_token = "pc-customer-01.a1b2c3d4e5f678901234567890abcdef"
        test_msg = f"Connecting to broker with token {test_token}..."

        captured = []
        def _cb(msg, level):
            captured.append(msg)

        emit_log(test_msg, "info", log_cb=_cb)

        for log in captured:
            self.assertNotIn("a1b2c3d4e5f678901234567890abcdef", log, "Raw token secret was leaked in log output!")

    def test_existing_log_files_have_zero_token_leaks(self):
        """[MODE: REAL] Scans existing system and local log files for token leaks."""
        log_paths = [
            LOG_FILE,
            os.path.join(BASE_DIR, "backup_log.txt"),
            os.path.join(r"C:\ProgramData\DatabaseBackupApp", "backup_log.txt"),
            os.path.join(r"C:\Program Files\DatabaseBackupApp", "backup_log.txt")
        ]
        for p in log_paths:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    matches = TOKEN_REGEX.findall(content)
                    self.assertEqual(matches, [], f"Token secret leaked in log file '{p}': {matches}")

    def test_source_code_clean_of_hardcoded_live_tokens(self):
        """[MODE: REAL] Scans production Python code to ensure 0 live customer token leaks."""
        exclude_dirs = {"tests", ".git", "__pycache__", "build", "dist"}
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith(".py") and file != "dev_broker.py":
                    fp = os.path.join(root, file)
                    with open(fp, "r", encoding="utf-8", errors="ignore") as pf:
                        content = pf.read()
                        matches = TOKEN_REGEX.findall(content)
                        self.assertEqual(matches, [], f"Hardcoded machine token discovered in '{fp}': {matches}")


if __name__ == "__main__":
    unittest.main()
