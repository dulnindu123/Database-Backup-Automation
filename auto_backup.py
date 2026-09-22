"""
Enterprise Database Cloud Backup Automation
Dual-Mode Application:
- Desktop GUI Application (Default on double-click or shortcut)
- Silent Scheduled Task Runner (When invoked with --auto by Task Scheduler)
"""

import os
import sys
import logging
from datetime import datetime

# Allow OAuth scope relaxation
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# Protect against None stdout/stderr in windowed/noconsole executables
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')


# Core modules
from backup_core import (
    BASE_DIR,
    LOG_FILE,
    load_config,
    authenticate,
    run_full_backup,
    emit_log
)

def run_automated_mode():
    """Silent automated execution designed for Windows Task Scheduler."""
    emit_log("=" * 60)
    emit_log("TASK SCHEDULER INVOCATION: --auto flag detected")
    emit_log("=" * 60)

    config = load_config()
    strictly_mondays = config.get("STRICTLY_MONDAYS_ONLY", True)
    
    # Monday check (weekday() == 0 for Monday)
    if strictly_mondays and datetime.today().weekday() != 0:
        emit_log(f"Today is {datetime.today().strftime('%A')}. Backup configured for Mondays only. Exiting safely.")
        sys.exit(0)

    emit_log("Monday check passed (or restriction disabled). Running automated backup...")
    
    # Authenticate non-interactively (uses token.json)
    creds = authenticate(interactive=False)
    if not creds:
        emit_log("Task Scheduler failed: Could not obtain valid Google Credentials (token.json).", "critical")
        sys.exit(1)

    success, summary = run_full_backup(config=config)
    emit_log(f"Automated backup result: {summary}")
    sys.exit(0 if success else 1)

def run_manual_cli():
    """Manual terminal CLI runner."""
    print("=" * 60)
    print("  DATABASE CLOUD BACKUP - CLI MANUAL MODE")
    print("=" * 60)
    config = load_config()
    creds = authenticate(interactive=True)
    if not creds:
        print("Error: Could not authenticate with Google.")
        sys.exit(1)
        
    success, summary = run_full_backup(config=config)
    print(f"\nResult: {summary}")
    sys.exit(0 if success else 1)

def main():
    # Detect execution mode from CLI arguments
    if "--auto" in sys.argv or "-a" in sys.argv:
        run_automated_mode()
    elif "--manual-cli" in sys.argv or "--cli" in sys.argv:
        run_manual_cli()
    else:
        # Launch Desktop GUI Application
        try:
            from app_gui import BackupAutomationApp
            app = BackupAutomationApp()
            app.mainloop()
        except Exception as e:
            emit_log(f"Failed to launch GUI, falling back to CLI menu: {e}", "error")
            run_manual_cli()

if __name__ == "__main__":
    main()
