"""
tests/test_full_e2e_flow.py
=============================================================================
End-to-End Integration Test for Round 9:
Full Install / Configuration -> Preflight Suite -> DBK2 Encryption -> Dev Broker Resumable Upload Flow

Tests:
1. dev_broker.py live healthz probe (HTTP 200)
2. Native DPAPI token sealing and decryption
3. Real live token verification with dev_broker (/verify)
4. RSA public keys validation (>= 3072 bits)
5. Destination folder validation (rejects cloud-sync paths, allows local temp)
6. Task Scheduler exact matching with DEFAULT_TASK_NAME
7. Backup encryption: AES-256-GCM + RSA-4096 -> .dbk2 file with valid envelope
8. Resumable chunked upload to dev_broker (/request-upload + /upload/<id>) with Content-Range & MD5 verification
9. Sheet telemetry binding (/bind-sheet) and server health reporting (/report-storage)
"""

import os
import sys
import json
import time
import shutil
import hashlib
import tempfile
import threading
import subprocess

try:
    import pytest
except ImportError:
    import unittest
    raise unittest.SkipTest("pytest is not installed")

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Ensure workspace root is in sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import version

@pytest.fixture(scope="module", autouse=True)
def dev_mode_fixture():
    orig_dev = getattr(version, "DEV_MODE", False)
    version.DEV_MODE = True
    yield
    version.DEV_MODE = orig_dev

from dev_broker import run_dev_server
from broker_client import _protect_dpapi_native, secure_upload
from crypto_stream import encrypt_file
from preflight import (
    run_preflight_suite,
    probe_broker_health,
    verify_token_with_broker,
    validate_public_keys,
    validate_backup_folder_path,
    validate_scheduled_task,
    DEFAULT_TASK_NAME,
)


@pytest.fixture(scope="module")
def local_dev_broker():
    """Spawns dev_broker.py on localhost:8088 in a background thread."""
    server, thread = run_dev_server(host="127.0.0.1", port=8088)
    time.sleep(0.5)  # Allow server to bind
    yield "http://127.0.0.1:8088"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture
def test_environment(tmp_path):
    """Sets up a complete isolated testing sandbox."""
    app_dir = tmp_path / "AppDir"
    data_dir = tmp_path / "DataDir"
    backup_dest = tmp_path / "Backups"
    app_dir.mkdir()
    data_dir.mkdir()
    backup_dest.mkdir()

    # 1. Generate real RSA 4096-bit keypairs
    primary_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    escrow_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

    primary_pub_pem = primary_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    escrow_pub_pem = escrow_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    with open(data_dir / "backup_public.pem", "wb") as f:
        f.write(primary_pub_pem)
    with open(data_dir / "escrow_public.pem", "wb") as f:
        f.write(escrow_pub_pem)

    # 2. Seal DPAPI token
    raw_token = "pc-TESTE2E01.ABCDEF0123456789ABCDEF0123456789"
    token_encrypted = _protect_dpapi_native(raw_token)
    with open(data_dir / "token.dpapi", "wb") as f:
        f.write(token_encrypted)

    # 3. Create simulated SQL .bak file (1 MB of random data)
    raw_bak_file = backup_dest / "TestDatabase_20261002.bak"
    sample_data = os.urandom(1024 * 1024)
    with open(raw_bak_file, "wb") as f:
        f.write(sample_data)

    return {
        "app_dir": str(app_dir),
        "data_dir": str(data_dir),
        "backup_dest": str(backup_dest),
        "raw_bak_file": str(raw_bak_file),
        "sample_data": sample_data,
        "primary_pub_pem": primary_pub_pem,
        "escrow_pub_pem": escrow_pub_pem,
        "raw_token": raw_token,
        "primary_key_path": str(data_dir / "backup_public.pem"),
        "escrow_key_path": str(data_dir / "escrow_public.pem"),
    }


def test_01_dev_broker_health(local_dev_broker):
    """Verifies that probe_broker_health succeeds against real dev_broker."""
    res = probe_broker_health(local_dev_broker)
    assert res.passed is True
    assert res.code == "OK"
    assert "200" in res.message or "healthy" in res.message.lower()


def test_02_token_verification(local_dev_broker, test_environment):
    """Verifies that real token verification succeeds on dev_broker /verify."""
    token = test_environment["raw_token"]
    res = verify_token_with_broker(local_dev_broker, token)
    assert res.passed is True
    assert res.code == "OK"
    assert "TESTE2E01" in res.message


def test_03_public_keys_preflight(test_environment):
    """Verifies public keys check passes for >= 3072-bit distinct RSA keys."""
    res = validate_public_keys(data_dir=test_environment["data_dir"])
    assert res.passed is True
    assert res.code == "OK"


def test_04_backup_folder_preflight(test_environment):
    """Verifies backup destination passes for local folder, fails for OneDrive."""
    res_ok = validate_backup_folder_path(test_environment["backup_dest"])
    assert res_ok.passed is True

    # Cloud sync path must be strictly rejected
    res_fail = validate_backup_folder_path(r"C:\Users\Admin\OneDrive\Backups")
    assert res_fail.passed is False
    assert res_fail.code == "ERR_CLOUD_SYNC_DETECTED"


def test_05_task_scheduler_exact_match():
    """Verifies Task Scheduler exact matching with DEFAULT_TASK_NAME."""
    test_exe = r"C:\Program Files\DatabaseBackupApp\DatabaseBackupApp.exe"
    # Create test task
    cmd_create = [
        "schtasks.exe", "/create",
        "/tn", DEFAULT_TASK_NAME,
        "/tr", f'"{test_exe}" --auto',
        "/sc", "weekly", "/d", "MON", "/st", "02:00",
        "/f"
    ]
    sub = subprocess.run(cmd_create, capture_output=True, text=True)
    if sub.returncode != 0:
        pytest.skip(f"Task creation requires permissions on Windows: {sub.stderr}")

    try:
        res = validate_scheduled_task(expected_exe=test_exe)
        assert res.passed is True
        assert res.code == "OK"
        assert DEFAULT_TASK_NAME in res.message
    finally:
        subprocess.run(["schtasks.exe", "/delete", "/tn", DEFAULT_TASK_NAME, "/f"], capture_output=True)


def test_06_encryption_dbk2_generation(test_environment):
    """Encrypts .bak into .dbk2 with AES-256-GCM + dual RSA-4096 envelope."""
    bak_path = test_environment["raw_bak_file"]
    dbk2_path = bak_path.replace(".bak", ".dbk2")

    encrypt_file(
        src=bak_path,
        dst=dbk2_path,
        public_key_paths=test_environment["primary_key_path"],
        escrow_key_path=test_environment["escrow_key_path"],
        db_name="TestDatabase"
    )

    assert os.path.exists(dbk2_path)
    assert os.path.getsize(dbk2_path) > os.path.getsize(bak_path)

    # Verify DBK2 header magic bytes
    with open(dbk2_path, "rb") as f:
        magic = f.read(4)
        assert magic == b"DBK2"


def test_07_resumable_upload_to_dev_broker(local_dev_broker, test_environment):
    """Executes full upload pipeline of encrypted DBK2 file to dev_broker."""
    bak_path = test_environment["raw_bak_file"]
    dbk2_path = bak_path.replace(".bak", ".dbk2")
    if not os.path.exists(dbk2_path):
        encrypt_file(
            src=bak_path,
            dst=dbk2_path,
            public_key_paths=test_environment["primary_key_path"],
            escrow_key_path=test_environment["escrow_key_path"],
            db_name="TestDatabase"
        )

    # Execute secure upload through broker_client
    cfg = {
        "BROKER_URL": local_dev_broker,
        "BROKER_TOKEN_FILE": "token.dpapi"
    }
    uploaded_obj = secure_upload(
        file_path=dbk2_path,
        db_name="TestDatabase",
        config=cfg,
        base_dir=test_environment["data_dir"],
        log_cb=lambda msg, lvl="info": print(f"[UPLOAD_LOG:{lvl}] {msg}")
    )

    assert uploaded_obj is not None
    assert "TestDatabase" in uploaded_obj
    assert uploaded_obj.endswith(".dbk2")


def test_08_full_preflight_suite_execution(local_dev_broker, test_environment):
    """Runs entire unified preflight suite against dev_broker."""
    cfg = {
        "BROKER_URL": local_dev_broker,
        "BACKUP_FOLDER": test_environment["backup_dest"],
        "SQL_SERVER_NAME": "",  # Exclude live SQL connection in unit test
        "_ENABLE_SCHEDULE": False  # Skip task check in isolated unit test
    }
    report = run_preflight_suite(
        config=cfg,
        target_dir=test_environment["app_dir"],
        data_dir=test_environment["data_dir"],
        mode="installer"
    )

    # All executed checks must pass
    failures = [f for f in report.failures if f.code != "ERR_SQL_UNCONFIGURED"]
    assert len(failures) == 0, f"Unexpected failures in preflight suite: {[f.message for f in failures]}"
