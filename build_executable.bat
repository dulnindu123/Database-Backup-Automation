@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   ZERO-TRUST SECURE BUILD ENGINE (v4.0.0)
echo   Enterprise Database Cloud Backup Automation
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/5] Verifying icon & branding assets...
if not exist "app_icon.ico" (
    python create_icon.py
)

echo [2/5] Compiling Main Application & Setup Wizard with PyInstaller (onedir mode)...
python -m PyInstaller --noconfirm --clean DatabaseBackupApp.spec
python -m PyInstaller --noconfirm --clean Setup_DatabaseBackup.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller compilation failed!
    exit /b %ERRORLEVEL%
)

echo [3/5] Bundling runtime templates and public RSA encryption keys (Primary + Escrow)...
if not exist "dist\DatabaseBackupApp\config.json" copy "config.json" "dist\DatabaseBackupApp\" >nul 2>&1
if exist "backup_public.pem" copy "backup_public.pem" "dist\DatabaseBackupApp\" >nul 2>&1
if exist "escrow_public.pem" copy "escrow_public.pem" "dist\DatabaseBackupApp\" >nul 2>&1

echo [4/5] Checking for Inno Setup Compiler (iscc.exe) to build clean installer...
set "ISCC_PATH="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"

if defined ISCC_PATH (
    echo       Compiling 0/71 Clean Inno Setup Installer...
    "!ISCC_PATH!" installer.iss >nul 2>&1
    if exist "dist_installer\Setup_DatabaseBackup_Clean.exe" (
        copy /y "dist_installer\Setup_DatabaseBackup_Clean.exe" "dist\Setup_DatabaseBackup.exe" >nul 2>&1
        echo       [SUCCESS] Clean Inno Setup Installer compiled to dist\Setup_DatabaseBackup.exe
    )
) else (
    echo       [NOTICE] Inno Setup [ISCC.exe] not found. PyInstaller onedir outputs placed in dist\
)

echo [5/5] Executing Build Secret Guard Audit (Zero-Trust Secret Scanner)...
python -c "
import os, sys

dist_dir = 'dist'
forbidden_files = ['client_secret.json', 'credentials.json', 'token.json', 'broker_token.dat', 'backup_log.txt']
violations = []

for root, dirs, files in os.walk(dist_dir):
    for f in files:
        if f in forbidden_files:
            violations.append(os.path.join(root, f))
        elif f.endswith('.pem'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                if 'PRIVATE KEY' in fp.read():
                    violations.append(path + ' (CONTAINS PRIVATE KEY)')

if violations:
    print('[CRITICAL ERROR] Secret guard failure! Discovered secrets in dist/:', violations)
    sys.exit(1)
else:
    print('[OK] Secret Guard Audit Passed: 0 secret files or private keys present in dist/')
"

if %ERRORLEVEL% NEQ 0 (
    echo [FATAL BUILD ERROR] Build aborted due to secret guard failure!
    exit /b 1
)

echo.
echo [CLEANUP] Purging build scratch files...
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1
if exist "dist_installer" rmdir /s /q "dist_installer" >nul 2>&1

echo.
echo ============================================================
echo   ZERO-TRUST BUILD COMPLETED SUCCESSFULLY!
echo   Main App: dist\DatabaseBackupApp\
echo   Installer: dist\Setup_DatabaseBackup\
echo ============================================================
