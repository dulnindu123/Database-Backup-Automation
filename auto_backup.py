"""
Enterprise Database Cloud Backup Automation - Application Entrypoint Router
=============================================================================
Author: Dulnindu Saranga
Target OS: Windows 10 / 11 / Windows Server
Architecture: Dual-Mode Application (GUI + Headless CLI / Task Scheduler)

Operational Modes:
1. Desktop GUI Mode (Default):
   Triggered on normal user invocation (double-clicking the desktop icon or 
   running without CLI flags). Initializes the CustomTkinter presentation layer.

2. Automated Headless Mode (--auto or -a):
   Triggered exclusively by Windows Task Scheduler (configured for Mondays at 02:00 AM).
   Operates silently without creating any graphical windows, evaluates the Monday 
   guard condition, performs the backup pipeline, logs telemetry, and exits with 
   an OS-level return code (0 = success, 1 = failure).

3. Manual CLI Mode (--manual-cli or --cli):
   Allows administrators or site engineers to run the backup interactively from 
   Command Prompt / PowerShell with terminal feedback.
"""

import os
import sys
import logging
from datetime import datetime

# -----------------------------------------------------------------------------
# GOOGLE OAUTH SCOPE RELAXATION
# -----------------------------------------------------------------------------
# Google Cloud periodically normalizes/consolidates legacy scope URLs.
# Setting this environment variable instructs oauthlib to accept modernized 
# canonical scopes returned by Google servers without raising a ScopeChangedError.
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

# -----------------------------------------------------------------------------
# WINDOWED EXECUTABLE STREAM SANITIZATION
# -----------------------------------------------------------------------------
# When compiled with PyInstaller using the --windowed / --noconsole flag,
# Windows does not attach a console subsystem. In this state, sys.stdout and 
# sys.stderr are None. Attempting to print() or flush() would raise an unhandled 
# AttributeError: 'NoneType' object has no attribute 'write'. 
# Redirecting to os.devnull ensures total runtime stability.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')


# -----------------------------------------------------------------------------
# CORE ENGINE IMPORTS
# -----------------------------------------------------------------------------
# backup_core is completely headless and thread-safe.
from backup_core import (
    BASE_DIR,
    LOG_FILE,
    load_config,
    authenticate,
    run_full_backup,
    emit_log
)


def run_automated_mode():
    """
    Executes the unattended, silent backup cycle for Windows Task Scheduler.
    
    Workflow:
    1. Read configuration (config.json).
    2. Enforce the Monday-only operational constraint (if enabled).
    3. Validate non-interactive Google OAuth credentials (credentials.json).
    4. Execute the complete backup, compression, cloud upload, and disk cleanup cycle.
    5. Terminate the process with exit code 0 (success) or 1 (failure) for OS monitoring.
    """
    emit_log("=" * 60)
    emit_log("TASK SCHEDULER INVOCATION: --auto flag detected")
    emit_log("=" * 60)

    config = load_config()
    strictly_mondays = config.get("STRICTLY_MONDAYS_ONLY", True)
    
    # In Python's datetime module: 0 = Monday, 1 = Tuesday, ..., 6 = Sunday.
    today_weekday = datetime.today().weekday()
    if strictly_mondays and today_weekday != 0:
        day_name = datetime.today().strftime('%A')
        emit_log(f"Today is {day_name}. Backup configured for Mondays only. Exiting safely with exit code 0.")
        sys.exit(0)

    emit_log("Monday check passed (or restriction disabled). Running automated backup...")
    
    # Authenticate non-interactively (uses cached refresh token from credentials.json).
    # interactive=False prevents the engine from trying to launch a web browser on an unattended server.
    creds = authenticate(interactive=False)
    if not creds:
        emit_log("Task Scheduler failed: Could not obtain valid Google Credentials (credentials.json missing or revoked).", "critical")
        sys.exit(1)

    # Run the full automated backup pipeline across all target databases
    success, summary = run_full_backup(config=config)
    emit_log(f"Automated backup result: {summary}")
    
    # Return explicit exit code to Windows Task Scheduler history
    sys.exit(0 if success else 1)


def run_manual_cli():
    """
    Executes an interactive terminal CLI session for manual server testing.
    Useful when remoted into a client server via SSH or PowerShell session.
    """
    print("=" * 60)
    print("  DATABASE CLOUD BACKUP - CLI MANUAL MODE")
    print("=" * 60)
    
    config = load_config()
    
    # In manual mode, interactive=True allows launching the browser if login is needed
    creds = authenticate(interactive=True)
    if not creds:
        print("Error: Could not authenticate with Google.")
        sys.exit(1)
        
    success, summary = run_full_backup(config=config)
    print(f"\nResult: {summary}")
    sys.exit(0 if success else 1)


def run_daemon_mode():
    """
    Continuous background daemon mode for Windows Service / Unattended Boot execution.
    Runs silently in Session 0, sleeps and awakens periodically.
    When the scheduled time arrives, it triggers the automated backup.
    """
    import time
    emit_log("=" * 60)
    emit_log("BACKGROUND SYSTEM SERVICE DAEMON INITIALIZED (SESSION 0)")
    emit_log("=" * 60)
    last_run_day = None
    while True:
        try:
            config = load_config()
            sched_time = config.get("SCHEDULE_TIME", "02:00")
            strictly_mondays = config.get("STRICTLY_MONDAYS_ONLY", True)
            
            now = datetime.now()
            today_weekday = now.weekday()
            cur_time_str = now.strftime("%H:%M")
            cur_day_key = now.strftime("%Y-%m-%d")
            
            day_matches = (not strictly_mondays) or (today_weekday == 0)
            time_matches = (cur_time_str == sched_time)
            
            if day_matches and time_matches and (last_run_day != cur_day_key):
                emit_log(f"Service trigger activated at {now}. Executing scheduled backup cycle...")
                creds = authenticate(interactive=False)
                if creds:
                    run_full_backup(config=config)
                    last_run_day = cur_day_key
                else:
                    emit_log("Service daemon failed: Google credentials missing or invalid.", "critical")
                    
            time.sleep(30)
        except Exception as e:
            emit_log(f"Service daemon error: {e}", "error")
            time.sleep(60)


def main():
    """
    Primary application entrypoint.
    Inspects sys.argv to dynamically route execution between GUI and CLI daemons.
    """
    # Route 1: Windows Task Scheduler execution
    if "--auto" in sys.argv or "-a" in sys.argv:
        run_automated_mode()
        
    # Route 2: Continuous background service daemon
    elif "--daemon" in sys.argv or "--service" in sys.argv:
        run_daemon_mode()

    # Route 3: Command-line terminal execution
    elif "--manual-cli" in sys.argv or "--cli" in sys.argv:
        run_manual_cli()
        
    # Route 3: Standard user desktop execution (default)
    else:
        try:
            from app_gui import BackupAutomationApp
            app = BackupAutomationApp()
            app.mainloop()
        except Exception as e:
            # Fallback to console error log if GUI display server fails to initialize
            emit_log(f"Failed to launch GUI, falling back to CLI menu: {e}", "error")
            run_manual_cli()


if __name__ == "__main__":
    main()
