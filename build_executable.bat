@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   BUILDING STANDALONE DATABASE BACKUP APPLICATION (.EXE)
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/3] Verifying icon files...
if not exist "app_icon.ico" (
    python create_icon.py
)

echo [2/3] Compiling with PyInstaller...
python -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --name "DatabaseBackupApp" ^
    --icon "app_icon.ico" ^
    --add-data "app_icon.ico;." ^
    --add-data "app_icon.png;." ^
    --collect-all "customtkinter" ^
    --collect-all "googleapiclient" ^
    --collect-all "gspread" ^
    --collect-all "google.auth" ^
    --collect-all "google_auth_oauthlib" ^
    "auto_backup.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] PyInstaller compilation failed!
    exit /b %ERRORLEVEL%
)

echo.
echo [3/4] Copying runtime configuration templates...
if not exist "dist\DatabaseBackupApp\config.json" copy "config.json" "dist\DatabaseBackupApp\"
if not exist "dist\DatabaseBackupApp\client_secret.json" copy "client_secret.json" "dist\DatabaseBackupApp\"
if exist "token.json" copy "token.json" "dist\DatabaseBackupApp\"

echo.
echo [4/4] Purging temporary build scratch files...
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1
del /f /q *.rartemp 2>nul
del /f /q ..\*.rartemp 2>nul
del /f /q ..\__rar_*.rartemp 2>nul
echo       Temporary scratch files purged. Final output kept in dist\

echo.
echo ============================================================
echo   BUILD COMPLETE!
echo   Output located in: dist\DatabaseBackupApp\
echo ============================================================
