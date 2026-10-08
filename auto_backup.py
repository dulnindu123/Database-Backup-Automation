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

# Configure Windows console streams for UTF-8 compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    broker_ready,
    run_full_backup,
    emit_log,
    # Section 9: Server Clean Up
    run_storage_monitor,
    # Module 3: Performance Query & Maintenance
    run_performance_query
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
    schedule_days = config.get("SCHEDULE_DAYS")
    if not schedule_days:
        strictly_mondays = config.get("STRICTLY_MONDAYS_ONLY", True)
        schedule_days = ["MON"] if strictly_mondays else ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    
    if isinstance(schedule_days, str):
        schedule_days = [d.strip().upper() for d in schedule_days.split(",") if d.strip()]
    else:
        schedule_days = [str(d).strip().upper() for d in schedule_days if str(d).strip()]
        
    today_code = datetime.today().strftime('%a').upper()  # 'MON', 'TUE', 'WED', etc.
    today_name = datetime.today().strftime('%A')
    
    is_allowed = (
        "DAILY" in schedule_days or 
        "ALL" in schedule_days or 
        "*" in schedule_days or 
        len(schedule_days) == 7 or 
        today_code in schedule_days
    )
    
    if not is_allowed:
        emit_log(f"Today is {today_name}. Automated backup is configured for {', '.join(schedule_days)}. Exiting safely with exit code 0.")
        sys.exit(0)

    emit_log(f"Schedule day check passed (Today is {today_name}). Running automated backup...")
    
    # Validate system state using shared preflight module (Requirement B)
    from preflight import run_preflight_suite
    report = run_preflight_suite(config, mode="scheduled_run")
    if not report.passed:
        first_fail = report.failures[0]
        failures_summary = " | ".join([f"{f.name} ({f.code}): {f.message}" for f in report.failures])
        emit_log(f"Preflight validation failed before scheduled run. Failing: {first_fail.name} ({first_fail.code}). All errors: {failures_summary}", "critical")
        sys.exit(1)

    # Run the full automated backup pipeline across all target databases
    success, summary = run_full_backup(config=config)
    emit_log(f"Automated backup result: {summary}")

    # Run the storage monitor after backup (piggyback scan)
    if config.get("STORAGE_MONITOR_ENABLED", True):
        emit_log("Running post-backup storage monitoring scan...")
        run_storage_monitor(config=config)
    
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
    ok, why = broker_ready(config)
    if not ok:
        print(f"Error: secure upload not configured: {why}")
        sys.exit(1)
        
    def cli_status(msg):
        print(f"  [STATUS] {msg}")

    success, summary = run_full_backup(config=config, status_cb=cli_status)
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
            schedule_days = config.get("SCHEDULE_DAYS")
            if not schedule_days:
                strictly_mondays = config.get("STRICTLY_MONDAYS_ONLY", True)
                schedule_days = ["MON"] if strictly_mondays else ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
                
            if isinstance(schedule_days, str):
                schedule_days = [d.strip().upper() for d in schedule_days.split(",") if d.strip()]
            else:
                schedule_days = [str(d).strip().upper() for d in schedule_days if str(d).strip()]

            now = datetime.now()
            today_code = now.strftime('%a').upper()
            cur_time_str = now.strftime("%H:%M")
            cur_day_key = now.strftime("%Y-%m-%d")
            
            day_matches = (
                "DAILY" in schedule_days or 
                "ALL" in schedule_days or 
                "*" in schedule_days or 
                len(schedule_days) == 7 or 
                today_code in schedule_days
            )
            time_matches = (cur_time_str == sched_time)
            
            if day_matches and time_matches and (last_run_day != cur_day_key):
                emit_log(f"Service trigger activated at {now}. Executing scheduled backup cycle...")
                ok, why = broker_ready(config)
                if ok:
                    run_full_backup(config=config)
                    last_run_day = cur_day_key
                else:
                    emit_log(f"Service daemon failed: secure upload not configured: {why}", "critical")
                    
            time.sleep(30)
        except Exception as e:
            emit_log(f"Service daemon error: {e}", "error")
            time.sleep(60)


def run_storage_scan_mode():
    """
    Standalone headless storage monitoring mode.
    Designed to be invoked by its own Windows Task Scheduler entry
    (Daily / Weekly / Monthly) independently from the backup schedule.
    
    Scans all drives, logs to Google Sheet, and sends email alerts if needed.
    """
    emit_log("=" * 60)
    emit_log("STANDALONE STORAGE MONITORING SCAN: --storage-scan flag detected")
    emit_log("=" * 60)

    config = load_config()
    
    if not config.get("STORAGE_MONITOR_ENABLED", True):
        emit_log("Storage monitoring is disabled in configuration. Exiting.")
        sys.exit(0)

    success, summary, drives, critical = run_storage_monitor(config=config)
    emit_log(f"Storage scan result: {summary}")
    sys.exit(0 if success else 1)


def run_performance_mode():
    """
    Standalone headless database performance maintenance & re-indexing mode.
    Can be invoked by Windows Task Scheduler (e.g. weekly maintenance) or CLI.
    Runs index fragmentation analysis, safety backup, DBCC CHECKDB, DBCC DBREINDEX, sp_updatestats,
    and telemetry reporting to Google Sheets.
    """
    emit_log("=" * 60)
    emit_log("DATABASE PERFORMANCE MAINTENANCE: --performance / --reindex flag detected")
    emit_log("=" * 60)

    config = load_config()
    target_dbs = config.get("TARGET_DATABASES", [])
    if not target_dbs and config.get("DATABASE_NAME"):
        target_dbs = [config.get("DATABASE_NAME")]
    if not target_dbs:
        target_dbs = ["TheDatabase"]

    overall_success = True
    for db in target_dbs:
        emit_log(f"Starting performance maintenance suite for [{db}]...")
        res = run_performance_query(
            config=config,
            target_db=db,
            mode="Scheduled",
            skip_backup=False,
            fill_factor=80
        )
        if not res.get("success", False):
            overall_success = False
            emit_log(f"Performance maintenance finished with warnings/errors for [{db}]: {res.get('summary')}", "warning")
        else:
            emit_log(f"Performance maintenance succeeded for [{db}]: {res.get('summary')}", "info")

    sys.exit(0 if overall_success else 1)


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

    # Route 3: Standalone storage monitoring scan
    elif "--storage-scan" in sys.argv:
        run_storage_scan_mode()

    # Route 4: Standalone performance query & re-indexing maintenance
    elif "--performance" in sys.argv or "--reindex" in sys.argv:
        run_performance_mode()

    # Route 5: Command-line terminal execution
    elif "--manual-cli" in sys.argv or "--cli" in sys.argv:
        run_manual_cli()

    # Route 5: Headless token provisioning on customer PC (used by installer without Python)
    elif "--import-token" in sys.argv:
        try:
            idx = sys.argv.index("--import-token")
            if idx + 1 >= len(sys.argv):
                print("[ERROR] --import-token requires a file path or token string argument.", file=sys.stderr)
                sys.exit(1)
            raw_input = sys.argv[idx + 1]
            from broker_client import import_and_protect_token
            from backup_core import DATA_DIR, load_config
            cfg = load_config()
            token_filename = cfg.get("BROKER_TOKEN_FILE", "token.dpapi")
            target_token_path = os.path.join(DATA_DIR, token_filename)
            import_and_protect_token(raw_input, target_token_path)
            print(f"[OK] Token imported and protected via DPAPI: {target_token_path}")
            sys.exit(0)
        except Exception as e:
            print(f"[ERROR] Failed to import token: {e}", file=sys.stderr)
            sys.exit(1)
        
    # Route 6: Standard user desktop execution (default)
    else:
        try:
            from app_gui import BackupAutomationApp
            app = BackupAutomationApp()
            app.mainloop()
        except Exception as e:
            import traceback
            err_trace = traceback.format_exc()
            try:
                emit_log(f"Critical error launching GUI:\n{err_trace}", "critical")
            except Exception:
                pass
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    f"Enterprise Database Cloud Backup could not initialize GUI.\n\nError: {e}\n\nPlease check backup_log.txt for full error details.",
                    "Database Cloud Backup - Initialization Error",
                    0x10
                )
            except Exception:
                pass
            if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                run_manual_cli()


if __name__ == "__main__":
    main()
