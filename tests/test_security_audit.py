import ast
import unittest
import os

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
                                if not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                                    rel = os.path.relpath(file_path, self.root_dir)
                                    violations.append(f"{rel}:{node.lineno} -> {func_name}(..., shell=NOT_FALSE)")

        self.assertGreater(len(files), 5, "Should scan at least 5 Python files")
        self.assertEqual(violations, [], f"Found shell=NOT_FALSE security violations:\\n" + "\\n".join(violations))

    def test_02_no_os_system_or_os_popen(self):
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

        self.assertEqual(violations, [], f"Found forbidden os.system / os.popen calls:\\n" + "\\n".join(violations))

    def test_03_no_string_form_subprocess_or_cmd_c(self):
        violations = []
        files = self._get_python_files()

        for file_path in files:
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
                            if isinstance(first_arg, (ast.Constant, ast.JoinedStr)):
                                violations.append(f"{rel}:{node.lineno} -> string command passed to {func_name}")
                            elif isinstance(first_arg, ast.List):
                                elements = []
                                for elt in first_arg.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        elements.append(elt.value.lower())
                                    elif isinstance(elt, ast.JoinedStr):
                                        elements.append("f-string")
                                if "cmd.exe" in elements or "cmd" in elements:
                                    if "/c" in elements:
                                        violations.append(f"{rel}:{node.lineno} -> cmd.exe /c call in {func_name}")

        self.assertEqual(violations, [], f"Found string-form or cmd.exe /c subprocess calls:\\n" + "\\n".join(violations))

    def test_04_no_google_credentials_in_client_packages(self):
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

        self.assertEqual(found_forbidden, [], f"Found forbidden secret files in client packages:\\n" + "\\n".join(found_forbidden))

    def test_06_acl_command_arguments_format(self):
        import backup_core
        from broker_client import secure_token_file_acl
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"dummy token data")
            tpath = tf.name

        try:
            secure_token_file_acl(tpath)
            self.assertTrue(os.path.exists(tpath))
        finally:
            if os.path.exists(tpath):
                os.remove(tpath)

if __name__ == '__main__':
    unittest.main()
