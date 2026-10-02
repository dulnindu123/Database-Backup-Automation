"""
Single Source of Truth for Application Versioning & Identity
=============================================================================
Centralizes version constants, executable names, and default paths across
the entire system (Core Engine, GUI, Installer, Build Pipeline, and Audit).
"""

APP_VERSION = "4.1.0"
INSTALLER_VERSION = "4.1.0"
APP_NAME = "Enterprise Database Cloud Backup"
EXE_NAME = "DatabaseBackupApp.exe"
INSTALLER_EXE_NAME = "Setup_DatabaseBackup.exe"

# Standard Production Paths (Requirement D)
DEFAULT_INSTALL_SUBDIR = "DatabaseBackupApp"
PROGRAM_DATA_DIR = r"C:\ProgramData\DatabaseBackupApp"
DEFAULT_TASK_NAME = r"\DatabaseBackupApp\DatabaseBackupAutoTask"
