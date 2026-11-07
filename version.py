"""
Single Source of Truth for Application Versioning & Identity
=============================================================================
Centralizes version constants, executable names, and default paths across
the entire system (Core Engine, GUI, Installer, Build Pipeline, and Audit).
"""

APP_VERSION = "5.0.0"
INSTALLER_VERSION = "5.0.0"
APP_NAME = "Enterprise Database Cloud Backup"
EXE_NAME = "DatabaseBackupApp.exe"
INSTALLER_EXE_NAME = "Setup_DatabaseBackup.exe"

# Standard Production Paths (Requirement D)
DEFAULT_INSTALL_SUBDIR = "DatabaseBackupApp"
PROGRAM_DATA_DIR = r"C:\ProgramData\DatabaseBackupApp"
DEFAULT_TASK_NAME = "Database Cloud Backup"

# Single Source of Truth for Build ID
BUILD_ID = "5.0.0-20261104"
BUILD_TIME = "2026-11-04T10:30:00Z"
BUILD_COMMIT = "v5.0-rel"
DEV_MODE = False

def get_build_info():
    """Retrieves authoritative build metadata from build_info.json if present."""
    import os
    import json
    candidates = [
        os.path.join(os.path.dirname(__file__), "build_info.json"),
        os.path.join(os.path.dirname(__file__), "AppFiles", "build_info.json"),
        os.path.join(os.getcwd(), "build_info.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {
        "version": APP_VERSION,
        "build_id": BUILD_ID,
        "build_time": BUILD_TIME,
        "short_hash": BUILD_COMMIT,
    }

def get_build_id() -> str:
    """Returns raw build ID string."""
    info = get_build_info()
    return info.get("build_id", BUILD_ID)

def get_display_version() -> str:
    """Returns detailed display string with version, build ID, and timestamp."""
    info = get_build_info()
    return f"v{info.get('version', APP_VERSION)} [{info.get('build_id', BUILD_ID)} - {info.get('build_time', BUILD_TIME)}]"

# Embedded Admin Ed25519 Public Key for Zero-Trust Manifest Verification
EMBEDDED_ADMIN_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAUwmpkX+0AVBJiRNUfd7tm65krqq30q7ngVYVgFzmGYk=\n"
    "-----END PUBLIC KEY-----"
)
