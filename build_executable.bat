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
copy /y "config.json" "dist\DatabaseBackupApp\config.json" >nul 2>&1
if exist "backup_public.pem" copy /y "backup_public.pem" "dist\DatabaseBackupApp\" >nul 2>&1
if exist "escrow_public.pem" copy /y "escrow_public.pem" "dist\DatabaseBackupApp\" >nul 2>&1

echo [4/5] Executing Build Secret Guard Audit (Zero-Trust Secret Scanner)...
python audit_build.py

if %ERRORLEVEL% NEQ 0 (
    echo [FATAL BUILD ERROR] Build aborted due to secret guard failure!
    exit /b 1
)

echo [5/5] Synchronizing production binaries to Client_Installation_Package...
set "PKG_DIR=..\Client_Installation_Package"
if exist "%PKG_DIR%" (
    if not exist "%PKG_DIR%\AppFiles" mkdir "%PKG_DIR%\AppFiles"
    robocopy.exe "dist\DatabaseBackupApp" "%PKG_DIR%\AppFiles" /MIR /IS /IT >nul
    if exist "dist\Setup_DatabaseBackup.exe" copy /y "dist\Setup_DatabaseBackup.exe" "%PKG_DIR%\Setup_DatabaseBackup.exe" >nul
    echo       [OK] Synchronized dist\DatabaseBackupApp to %PKG_DIR%\AppFiles
    echo       [OK] Synchronized Setup_DatabaseBackup.exe to %PKG_DIR%
)

:: Also update local test directory
set "LOCAL_APP=%LOCALAPPDATA%\Programs\DatabaseBackupApp"
if exist "%LOCAL_APP%" (
    taskkill.exe /F /IM DatabaseBackupApp.exe >nul 2>&1
    robocopy.exe "dist\DatabaseBackupApp" "%LOCAL_APP%" /E /IS /IT >nul
    echo       [OK] Synchronized local testing directory: %LOCAL_APP%
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
echo   Installer: dist\Setup_DatabaseBackup.exe
echo   Package: %PKG_DIR%
echo ============================================================

