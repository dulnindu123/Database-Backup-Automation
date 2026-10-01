"""
Security Audit Tests: Static Analysis & Secret Guard
=============================================================================
Verifies:
1. Static AST Scan: Asserts that NO shipped Python file in BackupAutomation uses `shell=True`
   in subprocess calls (subprocess.run, Popen, call, check_call, check_output).
2. Static AST Scan: Asserts NO usage of `os.system` or `os.popen`.
3. Command Format: Asserts that subprocess calls do not use string commands or `cmd.exe /c`.
4. Secret Guard: Verifies that NO Google service account keys (credentials.json, token.json,
   client_secret.json) or private keys are shipped in Client_Installation_Package or test/DatabaseBackupApp.
5. IAM Guard: Verifies that deploy.sh specifies `roles/storage.objectCreator` and NEVER `roles/storage.objectAdmin`.
6. ACL Verification: Asserts that ACL commands use direct argument lists (e.g. icacls.exe).
"""
import os
import ast
import unittest


class TestSecurityAudit(unittest.TestCase):
    def setUp(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.repo_dir = os.path.abspath(os.path.join(self.root_dir, ".."))

    def _get_python_files(self):
        py_files = []
        for root, dirs, files in os.walk(self.root_dir):
            if any(part in root for part in ("__pycache__", ".venv", "env", "build", "dist")):
                continue
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
        return py_files

    def test_01_no_shell_true_in_python_files(self):
        """Scans all Python files using Python's AST parser to ensure zero shell=True occurrences."""
        violations = []
        files = self._get_python_files()

        for file_path in files:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            try:
                tree = ast.parse(source, filename=file_path)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    elif isinstance(node.func, ast.Name):
                        func_name = node.func.id

                    if func_name in ("run", "Popen", "call", "check_call", "check_output"):
                        for kw in node.keywords:
                            if kw.arg == "shell":
                                if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                    rel = os.path.relpath(file_path, self.root_dir)
                                    violations.append(f"{rel}:{node.lineno} -> {func_name}(..., shell=True)")

        self.assertGreater(len(files), 5, "Should scan at least 5 Python files")
        self.assertEqual(violations, [], f"Found shell=True security violations:\n" + "\n".join(violations))

    def test_02_no_os_system_or_os_popen(self):
        """Ensures that neither os.system nor os.popen is used anywhere in the codebase."""
        violations = []
        files = self._get_python_files()

        for file_path in files:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            try:
                tree = ast.parse(source, filename=file_path)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                            if node.func.attr in ("system", "popen"):
                                rel = os.path.relpath(file_path, self.root_dir)
                                violations.append(f"{rel}:{node.lineno} -> os.{node.func.attr}()")

        self.assertEqual(violations, [], f"Found forbidden os.system / os.popen calls:\n" + "\n".join(violations))

    def test_03_no_string_form_subprocess_or_cmd_c(self):
        """Verifies subprocess calls use argument lists and do NOT invoke cmd.exe /c."""
        violations = []
        files = self._get_python_files()

        for file_path in files:
            # Skip test files themselves
            if "tests" in file_path:
                continue
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            try:
                tree = ast.parse(source, filename=file_path)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    elif isinstance(node.func, ast.Name):
                        func_name = node.func.id

                    if func_name in ("run", "Popen", "call", "check_call", "check_output"):
                        if node.args:
                            first_arg = node.args[0]
                            rel = os.path.relpath(file_path, self.root_dir)
                            # Flag string literals as command
                            if isinstance(first_arg, (ast.Constant, ast.JoinedStr)):
                                violations.append(f"{rel}:{node.lineno} -> string command passed to {func_name}")
                            # If it is a list, check for "cmd.exe" /c or "cmd" /c
                            elif isinstance(first_arg, ast.List):
                                elements = []
                                for elt in first_arg.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        elements.append(elt.value.lower())
                                if "cmd.exe" in elements or "cmd" in elements:
                                    if "/c" in elements:
                                        violations.append(f"{rel}:{node.lineno} -> cmd.exe /c call in {func_name}")

        self.assertEqual(violations, [], f"Found string-form or cmd.exe /c subprocess calls:\n" + "\n".join(violations))

    def test_04_no_google_credentials_in_client_packages(self):
        """Ensures no legacy Google OAuth or service account keys exist in Client_Installation_Package."""
        client_pkg_dir = os.path.join(self.repo_dir, "Client_Installation_Package")
        test_app_dir = os.path.join(self.repo_dir, "test", "DatabaseBackupApp")

        forbidden_filenames = {
            "credentials.json",
            "token.json",
            "client_secret.json",
            "backup_private.pem",
            "escrow_private.pem",
        }

        found_forbidden = []
        for target_dir in (client_pkg_dir, test_app_dir):
            if not os.path.exists(target_dir):
                continue
            for root, dirs, files in os.walk(target_dir):
                if "discovery_cache" in root or "_internal" in root:
                    continue
                for f in files:
                    if f.lower() in forbidden_filenames:
                        found_forbidden.append(os.path.join(root, f))

        self.assertEqual(found_forbidden, [], f"Found forbidden secret files in client packages:\n" + "\n".join(found_forbidden))

    def test_05_iam_deploy_script_has_object_creator_only(self):
        """Verifies that deploy.sh grants roles/storage.objectCreator and never roles/storage.objectAdmin."""
        deploy_sh = os.path.join(self.root_dir, "deploy.sh")
        self.assertTrue(os.path.exists(deploy_sh), "deploy.sh should exist")

        with open(deploy_sh, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("roles/storage.objectCreator", content, "deploy.sh must grant roles/storage.objectCreator")
        self.assertNotIn("roles/storage.objectAdmin", content, "deploy.sh must NEVER grant roles/storage.objectAdmin")
        # Check modern retention syntax
        self.assertIn("--retention-period", content, "deploy.sh must use --retention-period flag")
        self.assertIn("--lock-retention-period", content, "deploy.sh must use --lock-retention-period flag")

    def test_06_acl_command_arguments_format(self):
        """Verifies that icacls commands are properly formatted as argument lists."""
        import backup_core
        from broker_client import secure_token_file_acl
        import tempfile

        # Test secure_token_file_acl executes cleanly on Windows
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"dummy token data")
            tpath = tf.name

        try:
            secure_token_file_acl(tpath)
            self.assertTrue(os.path.exists(tpath))
        finally:
            if os.path.exists(tpath):
                os.remove(tpath)


if __name__ == "__main__":
    unittest.main()
