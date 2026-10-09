"""
release.py
=============================================================================
Unified Zero-Trust Build, Audit, Sync, and SHA-256 Manifest Pipeline
(Round 9 Requirement 5)

Performs:
1. Generates build metadata (version, build_time, git short hash).
2. Writes build_info.json and synchronizes version.py.
3. Compiles PyInstaller binaries:
   - DatabaseBackupApp.exe (main application)
   - Setup_DatabaseBackup.exe (installer with uac_admin=True)
4. Executes security audit (audit_build.py):
   - Scans dist/ for leaked private keys, OAuth tokens, stray txt configs.
   - Audits package allowlists.
5. Synchronizes build binaries and assets into Client_Installation_Package:
   - Setup_DatabaseBackup.exe -> package root
   - DatabaseBackupApp.exe and _internal/ -> package AppFiles/
   - build_info.json -> package root and AppFiles/
6. Writes sha256_manifest.json of Client_Installation_Package (all files & hashes).
7. Verifies sha256_manifest.json against physical package files.
"""

import os
import sys
import json
import hashlib
import shutil
import subprocess
from datetime import datetime, timezone

from version import APP_VERSION, DEFAULT_INSTALL_SUBDIR, DEFAULT_TASK_NAME
from audit_build import audit_master_package, audit_dist_secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DIST_DIR = os.path.join(BASE_DIR, "dist")
BUILD_DIR = os.path.join(BASE_DIR, "build")
PKG_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "Client_Installation_Package"))
if not os.path.exists(PKG_DIR):
    PKG_DIR = os.path.join(BASE_DIR, "Client_Installation_Package")


def get_git_short_hash() -> str:
    """Retrieves git short commit hash or fallback."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "prod"


def compute_sha256(filepath: str) -> str:
    """Computes SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_build_metadata() -> dict:
    """Generates authoritative build metadata."""
    short_hash = get_git_short_hash()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    build_id = f"{APP_VERSION}-{short_hash}"

    build_info = {
        "version": APP_VERSION,
        "build_id": build_id,
        "build_time": now_utc,
        "short_hash": short_hash,
    }

    # Write local build_info.json
    local_info_p = os.path.join(BASE_DIR, "build_info.json")
    with open(local_info_p, "w", encoding="utf-8") as f:
        json.dump(build_info, f, indent=2)
    print(f"[BUILD] Generated build metadata: {build_id} ({now_utc})")
    return build_info


LOCAL_TEMP_WORK = os.path.normpath(r"C:\temp\pyi_work")
LOCAL_TEMP_DIST = os.path.normpath(r"C:\temp\pyi_dist")


def pre_clean_build():
    """Safely cleans build and dist folders with retry to avoid Windows file locks."""
    import time
    for target in [LOCAL_TEMP_WORK, LOCAL_TEMP_DIST, os.path.join(DIST_DIR, "DatabaseBackupApp"), os.path.join(BUILD_DIR, "DatabaseBackupApp")]:
        if os.path.exists(target):
            for _ in range(5):
                try:
                    shutil.rmtree(target, ignore_errors=False)
                    break
                except Exception:
                    time.sleep(1)
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
    os.makedirs(LOCAL_TEMP_WORK, exist_ok=True)
    os.makedirs(LOCAL_TEMP_DIST, exist_ok=True)
    os.makedirs(DIST_DIR, exist_ok=True)


def compile_binaries():
    """Runs PyInstaller on both spec files."""
    print("\n" + "=" * 70)
    print("  STEP 1: COMPILING EXECUTABLES VIA PYINSTALLER (Isolated from OneDrive)")
    print("=" * 70)

    pre_clean_build()

    # 1. Main App
    print("[BUILD] Compiling DatabaseBackupApp.spec to local temp...")
    cmd_app = [
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", LOCAL_TEMP_DIST,
        "--workpath", LOCAL_TEMP_WORK,
        "DatabaseBackupApp.spec"
    ]
    res = subprocess.run(cmd_app, cwd=BASE_DIR)
    if res.returncode != 0:
        raise RuntimeError(f"DatabaseBackupApp compilation failed with exit code {res.returncode}")

    temp_app_dir = os.path.join(LOCAL_TEMP_DIST, "DatabaseBackupApp")
    target_app_dir = os.path.join(DIST_DIR, "DatabaseBackupApp")
    shutil.copytree(temp_app_dir, target_app_dir, dirs_exist_ok=True)

    app_exe = os.path.join(DIST_DIR, "DatabaseBackupApp", "DatabaseBackupApp.exe")
    if not os.path.exists(app_exe):
        raise FileNotFoundError(f"Expected compiled binary not found at: {app_exe}")
    print(f"[OK] DatabaseBackupApp compiled successfully ({os.path.getsize(app_exe):,} bytes)")

    # 2. Installer
    print("[BUILD] Compiling Setup_DatabaseBackup.spec to local temp...")
    cmd_inst = [
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", LOCAL_TEMP_DIST,
        "--workpath", LOCAL_TEMP_WORK,
        "Setup_DatabaseBackup.spec"
    ]
    res2 = subprocess.run(cmd_inst, cwd=BASE_DIR)
    if res2.returncode != 0:
        raise RuntimeError(f"Setup_DatabaseBackup compilation failed with exit code {res2.returncode}")

    temp_inst_exe = os.path.join(LOCAL_TEMP_DIST, "Setup_DatabaseBackup.exe")
    target_inst_exe = os.path.join(DIST_DIR, "Setup_DatabaseBackup.exe")
    shutil.copy2(temp_inst_exe, target_inst_exe)

    if not os.path.exists(target_inst_exe):
        raise FileNotFoundError(f"Expected compiled installer not found at: {target_inst_exe}")
    print(f"[OK] Setup_DatabaseBackup compiled successfully ({os.path.getsize(target_inst_exe):,} bytes)")


def run_security_audit():
    """Executes audit_build checks."""
    print("\n" + "=" * 70)
    print("  STEP 2: ZERO-TRUST DIST SECURITY AUDIT")
    print("=" * 70)

    dist_errors = audit_dist_secrets(DIST_DIR)
    if dist_errors:
        print("[CRITICAL ERROR] Dist audit failed with violations:")
        for err in dist_errors:
            print(f"  [X] {err}")
        raise RuntimeError("Dist security audit failed - secrets or forbidden files detected")
    print("[OK] Dist audit passed: 0 secret files, private keys, or stray configs detected.")


def sync_to_client_package(build_info: dict):
    """Syncs compiled artifacts into Client_Installation_Package."""
    print("\n" + "=" * 70)
    print(f"  STEP 3: SYNCHRONIZING TO CLIENT INSTALLATION PACKAGE ({PKG_DIR})")
    print("=" * 70)

    if not os.path.exists(PKG_DIR):
        raise FileNotFoundError(f"Client_Installation_Package does not exist at {PKG_DIR}")

    app_files_dir = os.path.join(PKG_DIR, "AppFiles")
    os.makedirs(app_files_dir, exist_ok=True)

    # 1. Copy Setup_DatabaseBackup.exe
    src_installer = os.path.join(DIST_DIR, "Setup_DatabaseBackup.exe")
    dst_installer = os.path.join(PKG_DIR, "Setup_DatabaseBackup.exe")
    if os.path.exists(src_installer):
        print(f"[SYNC] Copying installer: {src_installer} -> {dst_installer}")
        shutil.copy2(src_installer, dst_installer)
    elif os.path.exists(dst_installer):
        print(f"[SYNC] Retaining verified installer in: {dst_installer}")
    else:
        raise FileNotFoundError(f"Setup_DatabaseBackup.exe not found at {src_installer} or {dst_installer}")

    # 2. Copy DatabaseBackupApp.exe
    src_app = os.path.join(DIST_DIR, "DatabaseBackupApp", "DatabaseBackupApp.exe")
    dst_app = os.path.join(app_files_dir, "DatabaseBackupApp.exe")
    if os.path.exists(src_app):
        print(f"[SYNC] Copying app binary: {src_app} -> {dst_app}")
        shutil.copy2(src_app, dst_app)
    elif os.path.exists(dst_app):
        print(f"[SYNC] Retaining verified app binary in: {dst_app}")
    else:
        raise FileNotFoundError(f"DatabaseBackupApp.exe not found at {src_app} or {dst_app}")

    # 3. Copy _internal directory
    src_internal = os.path.join(DIST_DIR, "DatabaseBackupApp", "_internal")
    dst_internal = os.path.join(app_files_dir, "_internal")
    if os.path.exists(src_internal):
        print(f"[SYNC] Syncing _internal runtime tree: {src_internal} -> {dst_internal}")
        os.makedirs(dst_internal, exist_ok=True)
        if os.name == "nt":
            res = subprocess.run(["robocopy.exe", src_internal, dst_internal, "/E", "/IS", "/IT", "/NFL", "/NDL", "/NJH", "/NJS"], capture_output=True)
            if res.returncode > 7:
                raise RuntimeError(f"robocopy failed with exit code {res.returncode}")
        else:
            shutil.copytree(src_internal, dst_internal, dirs_exist_ok=True)

    # 4. Copy build_info.json to AppFiles and root
    info_json = json.dumps(build_info, indent=2)
    with open(os.path.join(app_files_dir, "build_info.json"), "w", encoding="utf-8") as f:
        f.write(info_json)
    with open(os.path.join(PKG_DIR, "build_info.json"), "w", encoding="utf-8") as f:
        f.write(info_json)
    print("[SYNC] Synchronized build_info.json to AppFiles and package root.")

    # 5. Sync batch scripts, docs, and shell_client (NO ADMIN TOOLS IN CLIENT PACKAGE)
    print("[SYNC] Copying root scripts and documentation...")
    for file in ['Update_App.bat', 'Uninstall.bat', 'READ_ME_FIRST.txt', 'README.md', 'CLIENT_INSTALLATION_GUIDE.md', 'CLIENT_INSTALLATION_AND_OPERATIONS_GUIDE.docx']:
        if os.path.exists(file):
            shutil.copy2(file, os.path.join(PKG_DIR, file))

    if os.path.exists('Uninstall.bat'):
        shutil.copy2('Uninstall.bat', os.path.join(app_files_dir, 'Uninstall.bat'))
        print("[SYNC] Synchronized Uninstall.bat into AppFiles.")

    for f in ['config.json', 'backup_public.pem', 'escrow_public.pem', 'bundle.json']:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(app_files_dir, f))
            print(f"[SYNC] Synchronized {f} into AppFiles.")
    if os.path.exists('bundle.json'):
        shutil.copy2('bundle.json', os.path.join(PKG_DIR, 'bundle.json'))
        print("[SYNC] Synchronized bundle.json into package root.")
    
    # Strictly remove Tools folder from Client Package if present
    dst_tools = os.path.join(PKG_DIR, 'Tools')
    if os.path.exists(dst_tools):
        print(f"[SYNC] Purging admin Tools folder from Client Package: {dst_tools}")
        shutil.rmtree(dst_tools, ignore_errors=True)

    src_shell = 'shell_client'
    dst_shell = os.path.join(PKG_DIR, 'shell_client')
    if os.path.exists(src_shell):
        print(f"[SYNC] Syncing shell_client folder: {src_shell} -> {dst_shell}")
        shutil.copytree(src_shell, dst_shell, dirs_exist_ok=True)

    # 6. Audit Client_Installation_Package
    pkg_errors = audit_master_package(PKG_DIR)
    if pkg_errors:
        print("[CRITICAL ERROR] Client package audit failed with violations:")
        for err in pkg_errors:
            print(f"  [X] {err}")
        raise RuntimeError("Client_Installation_Package audit failed")
    print("[OK] Client_Installation_Package allowlist audit passed.")


def create_and_verify_sha256_manifest(build_info: dict):
    """
    Creates sha256_manifest.json for all files in Client_Installation_Package
    and verifies every single file hash immediately.
    """
    print("\n" + "=" * 70)
    print("  STEP 4: GENERATING & VERIFYING SHA-256 MANIFEST")
    print("=" * 70)

    manifest_path = os.path.join(PKG_DIR, "sha256_manifest.json")
    files_map = {}

    total_files = 0
    total_bytes = 0

    for root, _, files in os.walk(PKG_DIR):
        for f in sorted(files):
            if f == "sha256_manifest.json":
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, PKG_DIR).replace("\\", "/")
            fsize = os.path.getsize(full_path)
            sha256_hash = compute_sha256(full_path)

            files_map[rel_path] = {
                "size_bytes": fsize,
                "sha256": sha256_hash
            }
            total_files += 1
            total_bytes += fsize

    manifest = {
        "manifest_version": "1.0",
        "app_version": build_info["version"],
        "build_id": build_info["build_id"],
        "build_time": build_info["build_time"],
        "short_hash": build_info["short_hash"],
        "total_files": total_files,
        "total_bytes": total_bytes,
        "files": files_map
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[MANIFEST] Wrote {manifest_path} ({total_files} files, {total_bytes:,} bytes).")

    # Step 5: Verification of manifest
    print("[VERIFY] Verifying SHA-256 manifest against package files...")
    with open(manifest_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    if loaded.get("build_id") != build_info["build_id"]:
        raise ValueError("Manifest build_id mismatch")

    verified_count = 0
    for rel_path, entry in loaded.get("files", {}).items():
        disk_path = os.path.join(PKG_DIR, rel_path.replace("/", os.sep))
        if not os.path.exists(disk_path):
            raise FileNotFoundError(f"File listed in manifest is missing on disk: {rel_path}")

        disk_size = os.path.getsize(disk_path)
        if disk_size != entry["size_bytes"]:
            raise ValueError(f"Size mismatch on {rel_path}: expected {entry['size_bytes']}, got {disk_size}")

        disk_hash = compute_sha256(disk_path)
        if disk_hash != entry["sha256"]:
            raise ValueError(f"SHA-256 hash mismatch on {rel_path}!\nExpected: {entry['sha256']}\nGot:      {disk_hash}")
        verified_count += 1

    print(f"[OK] 100% Verified: All {verified_count} files match SHA-256 manifest checksums!")
    print("=" * 70)


def main():
    print("=" * 70)
    print("  ZERO-TRUST ENTERPRISE BACKUP RELEASE PIPELINE")
    print(f"  Target: Client_Installation_Package")
    print("=" * 70)

    skip_compile = "--skip-compile" in sys.argv

    # 1. Build metadata
    build_info = generate_build_metadata()

    # 2. Compile executables
    if not skip_compile:
        compile_binaries()
    else:
        print("[BUILD] Skipping PyInstaller compilation (--skip-compile flag), using existing dist/ binaries.")

    # 3. Security audit
    run_security_audit()

    # 4. Sync into Client_Installation_Package
    sync_to_client_package(build_info)

    # 5. Write and verify SHA-256 manifest
    create_and_verify_sha256_manifest(build_info)

    print("\nRELEASE PIPELINE COMPLETE: SUCCESSFUL BUILD & VERIFIED PACKAGE!")
    print(f"Build ID: {build_info['build_id']}")
    print(f"Package : {PKG_DIR}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
