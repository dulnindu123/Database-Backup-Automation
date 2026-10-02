@echo off
setlocal enabledelayedexpansion

echo ======================================================================
echo   ENTERPRISE DATABASE BACKUP: CLEAN-VM VALIDATION RUNNER
echo   Zero-Trust Verification Suite (Requirements B, D, E, H)
echo ======================================================================
echo.

:: 1. Check Administrator Elevation
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Running without Administrator privileges.
    echo        For full Task Scheduler SYSTEM tests, right-click and "Run as Administrator".
) else (
    echo [OK] Running with elevated Administrator privileges.
)

:: 2. Execute Clean VM Installation Unit Tests
echo.
echo [STEP 1/2] Running Clean-VM Install Assertions...
python -m unittest tests/test_clean_vm_install.py -v
if %errorlevel% neq 0 (
    echo [FAIL] Clean-VM install verification failed!
    exit /b 1
)

:: 3. Execute Failure Matrix (8 Modes, Real vs Mocked)
echo.
echo [STEP 2/2] Running Preflight Failure Matrix (8 Modes)...
python -m unittest tests/test_failure_matrix.py -v
if %errorlevel% neq 0 (
    echo [FAIL] Preflight Failure Matrix tests failed!
    exit /b 1
)

echo.
echo ======================================================================
echo   ALL CLEAN-VM TESTS COMPLETED SUCCESSFULLY
echo ======================================================================
exit /b 0
