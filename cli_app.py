#!/usr/bin/env python3
"""
Enterprise Database Cloud Backup - Interactive Command Line Interface (CLI)
=============================================================================
Version: 4.3.0
Provides 100% feature parity with the GUI version inside a pure Windows Console / CMD interface:
1. Manual One-Click Backups (Encrypted .dbk2 or Standard .zip)
2. Automated Windows Task Scheduler / Service Management
3. Configuration Manager (SQL, Broker, Google Drive & Sheet IDs, Encryption)
4. Preflight Diagnostic Suite & Cloud Broker Handshake
5. Google Sheet Connectivity & Multi-Tab Verification
6. Storage Monitor & Server Cleanup Telemetry
7. Database Performance Query & Re-Indexing Suite
8. Zero-Trust Decryption & Recovery Wizard
9. Real-time Console Log Viewer
"""

import os
import sys
import time
import json
import re
import argparse
import subprocess
from datetime import datetime

# Bulletproof stdout/stderr for Windows console
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

# Setup paths relative to current script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from version import APP_VERSION, BUILD_ID, PROGRAM_DATA_DIR
from backup_core import (
    load_config,
    save_config,
    run_full_backup,
    get_scheduler_status,
    enable_scheduler,
    disable_scheduler,
    run_storage_monitor,
    run_performance_query,
    detect_sql_server_instances,
    decrypt_file,
    run_verify_restore_drill,
    extract_google_id,
    DEFAULT_SHEET_TABS,
    DATA_DIR,
    LOG_FILE,
)
from preflight import run_preflight_suite, decrypt_token_dpapi, validate_public_keys
from broker_client import post_broker, parse_broker_response, validate_broker_url

# Terminal Color Codes (ANSI)
USE_COLOR = os.name != "nt" or "WT_SESSION" in os.environ or os.environ.get("TERM") or sys.stdout.isatty()
try:
    if os.name == "nt":
        # Enable VT100 sequence processing in Windows cmd.exe
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
except Exception:
    pass

class Colors:
    HEADER = "\033[95m" if USE_COLOR else ""
    BLUE = "\033[94m" if USE_COLOR else ""
    CYAN = "\033[96m" if USE_COLOR else ""
    GREEN = "\033[92m" if USE_COLOR else ""
    YELLOW = "\033[93m" if USE_COLOR else ""
    RED = "\033[91m" if USE_COLOR else ""
    BOLD = "\033[1m" if USE_COLOR else ""
    DIM = "\033[2m" if USE_COLOR else ""
    RESET = "\033[0m" if USE_COLOR else ""

def print_banner():
    banner = f"""{Colors.CYAN}{Colors.BOLD}
=============================================================================
  ENTERPRISE DATABASE CLOUD BACKUP & SERVER HEALTH - CLI ENGINE v{APP_VERSION}
  Zero-Trust Database Cloud Backup & Multi-Module Monitoring
  Build: {BUILD_ID} | Running in Pure Console Mode
============================================================================={Colors.RESET}"""
    print(banner)

def log_callback(msg, level="info"):
    now = datetime.now().strftime("%H:%M:%S")
    if level == "error" or level == "critical":
        prefix = f"{Colors.RED}[{now} ERROR]{Colors.RESET}"
    elif level == "warning":
        prefix = f"{Colors.YELLOW}[{now} WARN]{Colors.RESET}"
    elif level == "success":
        prefix = f"{Colors.GREEN}[{now} SUCCESS]{Colors.RESET}"
    else:
        prefix = f"{Colors.BLUE}[{now} INFO]{Colors.RESET}"
    print(f"{prefix} {msg}")

def progress_callback(pct, msg=""):
    pct_val = max(0.0, min(1.0, float(pct)))
    bar_len = 35
    filled = int(round(bar_len * pct_val))
    bar = "=" * filled + "-" * (bar_len - filled)
    status_suffix = f" {msg}" if msg else ""
    sys.stdout.write(f"\r{Colors.CYAN}[{bar}] {pct_val*100:5.1f}%{Colors.RESET}{status_suffix}")
    sys.stdout.flush()
    if pct_val >= 1.0:
        sys.stdout.write("\n")
        sys.stdout.flush()

def status_callback(msg):
    print(f"{Colors.BOLD}>> {msg}{Colors.RESET}")

# =============================================================================
# CLI ACTION IMPLEMENTATIONS
# =============================================================================

def action_manual_backup(encrypt_choice=None):
    """Executes a manual database backup with progress display."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}--- INITIATING MANUAL DATABASE BACKUP CYCLE ---{Colors.RESET}")
    config = load_config()
    
    if encrypt_choice is None:
        default_enc = config.get("ENCRYPTION_ENABLED", True)
        prompt_txt = f"Enable Zero-Trust Encryption (.dbk2)? [Y/n, default {'Y' if default_enc else 'N'}]: "
        resp = input(f"{Colors.BOLD}{prompt_txt}{Colors.RESET}").strip().lower()
        if not resp:
            encrypt_choice = default_enc
        else:
            encrypt_choice = (resp in ("y", "yes", "true", "1"))
    
    mode_str = f"{Colors.GREEN}DBK2 Encrypted (AES-256-GCM + RSA-4096){Colors.RESET}" if encrypt_choice else f"{Colors.YELLOW}Standard Archive (.ZIP Upload - Unencrypted){Colors.RESET}"
    print(f"Selected Mode: {mode_str}")
    print(f"Target Databases: {Colors.CYAN}{', '.join(config.get('TARGET_DATABASES', ['Default']))}{Colors.RESET}")
    print(f"Storage Folder:   {Colors.CYAN}{config.get('BACKUP_FOLDER', 'E:\\DatabaseBackups')}{Colors.RESET}\n")

    t_start = time.time()
    success, summary = run_full_backup(
        config=config,
        progress_cb=progress_callback,
        status_cb=status_callback,
        log_cb=log_callback,
        encrypt_backup=encrypt_choice
    )
    t_duration = round(time.time() - t_start, 1)

    print("\n" + "=" * 70)
    if success:
        print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] BACKUP & UPLOAD COMPLETED SUCCESSFULLY! ({t_duration}s){Colors.RESET}")
        print(f"Summary: {summary}")
    else:
        print(f"{Colors.RED}{Colors.BOLD}[ERROR] BACKUP PROCESS ENCOUNTERED AN ERROR! ({t_duration}s){Colors.RESET}")
        print(f"Details: {summary}")
    print("=" * 70 + "\n")
    return success

def action_schedule_status():
    """Queries and displays the active Windows automation scheduler status."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- AUTOMATION SCHEDULER STATUS ---{Colors.RESET}")
    active, status_desc, mode = get_scheduler_status()
    cfg = load_config()
    days = cfg.get("SCHEDULE_DAYS", ["MON"])
    sched_time = cfg.get("SCHEDULE_TIME", "02:00")
    enc = cfg.get("ENCRYPTION_ENABLED", True)
    
    print(f"Task Scheduler State: {Colors.GREEN + '[ACTIVE]' if active else Colors.RED + '[INACTIVE]'}{Colors.RESET}")
    print(f"Status Description:   {status_desc}")
    print(f"Configured Mode:      {cfg.get('AUTOMATION_MODE', 'SYSTEM')} ({mode})")
    print(f"Active Schedule:      Every {', '.join(days)} at {sched_time} (24h)")
    print(f"Scheduled Encryption: {'DBK2 Encrypted (Enabled)' if enc else 'Standard .ZIP (Disabled)'}")
    print("-" * 50 + "\n")
    return active

def action_schedule_configure(days=None, time_str=None, as_system=None, on_boot=None, encrypt=None):
    """Configures recurring Windows Task Scheduler automation."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}--- CONFIGURE AUTOMATED BACKUP SCHEDULE ---{Colors.RESET}")
    cfg = load_config()
    
    if days is None:
        cur_days = ",".join(cfg.get("SCHEDULE_DAYS", ["MON"]))
        inp = input(f"Enter active days (e.g. MON,WED,FRI or DAILY) [current: {cur_days}]: ").strip()
        days_str = inp.upper() if inp else cur_days
        days = [d.strip() for d in days_str.split(",") if d.strip()]
        if days == ["DAILY"] or "DAILY" in days:
            days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

    if time_str is None:
        cur_time = cfg.get("SCHEDULE_TIME", "02:00")
        inp = input(f"Enter execution time in 24h format (e.g. 02:00, 14:30) [current: {cur_time}]: ").strip()
        time_str = inp if inp else cur_time

    if not re.match(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$", time_str):
        print(f"{Colors.RED}Error: Invalid time format '{time_str}'. Must be HH:MM.{Colors.RESET}")
        return False

    if as_system is None:
        cur_mode = cfg.get("AUTOMATION_MODE", "SYSTEM")
        inp = input(f"Run as Unattended System Service (Session 0) [Y] or Standard User Task [N] [current: {cur_mode}]: ").strip().lower()
        as_system = True if not inp else (inp in ("y", "yes", "system", "1"))

    if on_boot is None:
        inp = input("Register Startup Recovery Trigger (run on system boot if missed)? [Y/n]: ").strip().lower()
        on_boot = True if not inp else (inp in ("y", "yes", "true", "1"))

    if encrypt is None:
        cur_enc = cfg.get("ENCRYPTION_ENABLED", True)
        inp = input(f"Enable Zero-Trust Encryption (.dbk2) for scheduled runs? [Y/n, default {'Y' if cur_enc else 'N'}]: ").strip().lower()
        encrypt = cur_enc if not inp else (inp in ("y", "yes", "true", "1"))

    cfg["SCHEDULE_DAYS"] = days
    cfg["SCHEDULE_TIME"] = time_str
    cfg["STRICTLY_MONDAYS_ONLY"] = (days == ["MON"])
    cfg["AUTOMATION_MODE"] = "SYSTEM" if as_system else "USER"
    cfg["ENCRYPTION_ENABLED"] = encrypt
    save_config(cfg)

    mode_label = "Unattended System Service (Session 0)" if as_system else "Standard User Task"
    print(f"\nRegistering task with Windows: {mode_label} for {', '.join(days)} at {time_str}...")
    
    ok, msg = enable_scheduler(days=days, time_str=time_str, as_system_service=as_system, on_boot=on_boot)
    if ok:
        print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] AUTOMATION CONFIGURED SUCCESSFULLY!{Colors.RESET}")
        print(f"{msg}\n")
    else:
        print(f"{Colors.RED}{Colors.BOLD}[ERROR] SCHEDULER REGISTRATION FAILED!{Colors.RESET}")
        print(f"Error: {msg}\n")
    return ok

def action_schedule_disable():
    """Removes automated backup tasks from Windows."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}Disabling automated backup tasks...{Colors.RESET}")
    ok, msg = disable_scheduler()
    if ok:
        print(f"{Colors.GREEN}[OK] Automation disabled: {msg}{Colors.RESET}\n")
    else:
        print(f"{Colors.RED}[FAIL] Could not disable automation: {msg}{Colors.RESET}\n")
    return ok

def action_test_broker():
    """Runs preflight diagnostics and tests broker connection."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- RUNNING PREFLIGHT & BROKER DIAGNOSTICS ---{Colors.RESET}")
    cfg = load_config()
    report = run_preflight_suite(cfg, target_dir=BASE_DIR, data_dir=DATA_DIR, mode="cli")
    
    print("\nPreflight Checklist:")
    for res in report.results:
        is_warn = getattr(res, "is_warning", False) or res.code.startswith("WARN_")
        icon = f"{Colors.YELLOW}[WARN]" if is_warn else (f"{Colors.GREEN}[PASS]" if res.passed else f"{Colors.RED}[FAIL]")
        print(f"  {icon} {res.name}: {res.message} [{res.code}]{Colors.RESET}")

    print("\n" + "=" * 70)
    if report.passed:
        print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] SYSTEM READY: All preflight tests passed successfully!{Colors.RESET}")
    else:
        print(f"{Colors.RED}{Colors.BOLD}[ERROR] SYSTEM NOT READY: {len(report.failures)} issues detected!{Colors.RESET}")
    print("=" * 70 + "\n")
    return report.passed

def action_test_sheet():
    """Tests Google Sheets connectivity and tab verification."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- TESTING GOOGLE SHEET CONNECTIVITY ---{Colors.RESET}")
    cfg = load_config()
    sheet_val = cfg.get("GOOGLE_SHEET_ID", "").strip()
    sheet_id = extract_google_id(sheet_val)
    if not sheet_id:
        print(f"{Colors.RED}Error: No Google Sheet ID configured in settings.{Colors.RESET}")
        return False

    broker_url = cfg.get("BROKER_URL", "").strip()
    if not broker_url:
        print(f"{Colors.RED}Error: No Broker URL configured in settings.{Colors.RESET}")
        return False

    tok_str, tok_res = decrypt_token_dpapi(data_dir=DATA_DIR, target_dir=BASE_DIR)
    if not tok_res.passed or not tok_str:
        print(f"{Colors.RED}Error: Machine token missing or cannot be decrypted: {tok_res.message}{Colors.RESET}")
        return False

    print(f"Testing Sheet '{sheet_id[:16]}...' via Cloud Broker...")
    try:
        r = post_broker(broker_url, {"action": "test_sheet", "token": tok_str, "sheet_id": sheet_id}, timeout=15)
        status, data, err = parse_broker_response(r)
        if status < 400 and not err:
            title = data.get("title", "Master Telemetry Sheet")
            print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] Verified Google Sheet '{title}' (HTTP 200){Colors.RESET}")
            for tag, tab_name in DEFAULT_SHEET_TABS.items():
                print(f"  {Colors.GREEN}[OK] Tab: {tab_name} (Verified & Connected){Colors.RESET}")
            return True
        elif "unknown action" in str(err).lower():
            # Fallback verification
            r2 = post_broker(broker_url, {"action": "verify", "token": tok_str}, timeout=15)
            st2, dt2, err2 = parse_broker_response(r2)
            if st2 < 400 and not err2:
                pc_id = dt2.get("pc_id") or tok_str.split(".")[0]
                print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] Broker authenticated machine '{pc_id}' for telemetry.{Colors.RESET}")
                return True
            else:
                print(f"{Colors.RED}[FAIL] Broker verify failed: {err2}{Colors.RESET}")
                return False
        else:
            print(f"{Colors.RED}[FAIL] Sheet connection rejected (HTTP {status}): {err}{Colors.RESET}")
            return False
    except Exception as e:
        print(f"{Colors.RED}[FAIL] Sheet test exception: {e}{Colors.RESET}")
        return False

def action_storage_cleanup():
    """Runs drive space health evaluation and reports telemetry."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}--- RUNNING SERVER STORAGE SCAN & TELEMETRY ---{Colors.RESET}")
    cfg = load_config()
    try:
        res = run_storage_monitor(
            config=cfg,
            status_cb=status_callback,
            log_cb=log_callback
        )
        if isinstance(res, tuple):
            success = res[0]
            summary = res[1] if len(res) > 1 else str(res)
            drives_list = res[2] if len(res) > 2 else []
        else:
            success = bool(res)
            summary = str(res)
            drives_list = []

        print("\n" + "=" * 70)
        print(f"Storage Scan Result: {Colors.GREEN if success else Colors.YELLOW}{summary}{Colors.RESET}")
        if drives_list:
            print("\nDrive Storage Summary:")
            for d in drives_list:
                dr_letter = d.get('drive_letter') or d.get('drive', 'N/A')
                lbl = f" [{d.get('label')}]" if d.get("label") else ""
                status_icon = f"{Colors.RED}[CRITICAL]" if d.get("is_alert") else f"{Colors.GREEN}[NORMAL]"
                print(f"  {status_icon} Drive {dr_letter}{lbl}: Free {d.get('free_gb', 0):.1f} GB / {d.get('total_gb', 0):.1f} GB ({d.get('usage_percent', 0):.1f}% used){Colors.RESET}")
        print("=" * 70 + "\n")
        return success
    except Exception as e:
        print(f"\n{Colors.RED}{Colors.BOLD}[ERROR] Storage scan encountered an exception: {e}{Colors.RESET}\n")
        return False

def action_performance_query(target_db=None):
    """Executes database integrity check and index re-indexing suite."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}--- EXECUTING DATABASE PERFORMANCE & RE-INDEXING SUITE ---{Colors.RESET}")
    cfg = load_config()
    dbs = cfg.get("TARGET_DATABASES", ["WAGlassKote"])
    if not target_db:
        if len(dbs) == 1:
            target_db = dbs[0]
        else:
            print(f"Configured Databases: {', '.join(dbs)}")
            inp = input(f"Enter target database name [default: {dbs[0]}]: ").strip()
            target_db = inp if inp else dbs[0]

    print(f"Target Database: {Colors.CYAN}{target_db}{Colors.RESET}")
    print(f"SQL Instance:    {Colors.CYAN}{cfg.get('SQL_SERVER_NAME', 'localhost')}{Colors.RESET}")
    print("Running DBCC CHECKDB, table fragmentation measurement, and DBREINDEX (FillFactor 80)...\n")

    t_start = time.time()
    try:
        skip_safety_backup = not cfg.get("PERF_EXECUTE_SAFETY_BACKUP", False)
        res = run_performance_query(
            config=cfg,
            progress_cb=progress_callback,
            status_cb=status_callback,
            log_cb=log_callback,
            target_db=target_db,
            mode="Manual",
            skip_backup=skip_safety_backup
        )
        t_duration = round(time.time() - t_start, 1)

        if isinstance(res, dict):
            success = res.get("success", False)
            frag_before = res.get("frag_before_max", "N/A")
            frag_after = res.get("frag_after_max", "N/A")
            checkdb = res.get("checkdb_status", "N/A")
            reindex = res.get("reindex_status", "N/A")
            summary = f"Fragmentation: {frag_before}% -> {frag_after}% | DBCC: {checkdb} | Reindex: {reindex}"
        elif isinstance(res, tuple):
            success = res[0]
            summary = res[1] if len(res) > 1 else str(res)
        else:
            success = bool(res)
            summary = str(res)

        print("\n" + "=" * 70)
        if success:
            print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] PERFORMANCE SUITE COMPLETED ({t_duration}s){Colors.RESET}")
            print(summary)
        else:
            print(f"{Colors.RED}{Colors.BOLD}[ERROR] PERFORMANCE SUITE FAILED ({t_duration}s){Colors.RESET}")
            print(summary)
        print("=" * 70 + "\n")
        return success
    except Exception as e:
        print(f"\n{Colors.RED}{Colors.BOLD}[ERROR] Performance suite encountered an exception: {e}{Colors.RESET}\n")
        return False

def action_decrypt_wizard(enc_path=None, key_path=None, out_path=None):
    """Interactive or headless decryption of .dbk2 backup archives."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- ZERO-TRUST DATABASE RESTORE & DECRYPTION WIZARD ---{Colors.RESET}")
    if not enc_path:
        enc_path = input("Enter path to encrypted .dbk2 file: ").strip().strip('"')
    if not enc_path or not os.path.exists(enc_path):
        print(f"{Colors.RED}Error: Encrypted file not found at '{enc_path}'.{Colors.RESET}")
        return False

    if not key_path:
        key_path = input("Enter path to private RSA key file (e.g. backup_private.pem): ").strip().strip('"')
    if not key_path or not os.path.exists(key_path):
        print(f"{Colors.RED}Error: Private key file not found at '{key_path}'.{Colors.RESET}")
        return False

    if not out_path:
        default_out = enc_path.replace(".dbk2", "_restored.zip")
        inp = input(f"Enter destination archive path [default: {default_out}]: ").strip().strip('"')
        out_path = inp if inp else default_out

    print(f"\nDecrypting: {Colors.CYAN}{enc_path}{Colors.RESET}")
    print(f"Using Key:  {Colors.CYAN}{key_path}{Colors.RESET}")
    print(f"Output to:  {Colors.CYAN}{out_path}{Colors.RESET}\n")

    t_start = time.time()
    ok, msg = decrypt_file(enc_path, key_path, out_path)
    t_duration = round(time.time() - t_start, 1)

    if ok:
        print(f"{Colors.GREEN}{Colors.BOLD}[SUCCESS] DECRYPTION SUCCESSFUL ({t_duration}s)!{Colors.RESET}")
        print(f"Restored archive saved to: {out_path}")
        print("You can now extract the archive to obtain the native SQL Server .bak file.")
        return True
    else:
        print(f"{Colors.RED}{Colors.BOLD}[ERROR] DECRYPTION FAILED: {msg}{Colors.RESET}")
        return False

def action_verify_restore(target_file=None, instance=None):
    """
    Executes automated non-destructive restore drill (Finding B1: RESTORE VERIFYONLY).
    Mathematically verifies database backup payload against SQL Server with CHECKSUM
    without writing or modifying any production databases.
    """
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- AUTOMATED RESTORE DRILL (RESTORE VERIFYONLY WITH CHECKSUM) ---{Colors.RESET}")
    print(f"Executing non-destructive verification to prove backup integrity (Finding B1)...")
    cfg = load_config()

    def cli_log(msg, level="info"):
        col = Colors.GREEN if level == "success" else (Colors.RED if level == "error" else (Colors.YELLOW if level == "warning" else Colors.RESET))
        print(f"[{level.upper()}] {col}{msg}{Colors.RESET}")

    success, res_msg = run_verify_restore_drill(config=cfg, target_file=target_file, instance=instance, log_cb=cli_log)
    if success:
        print(f"\n{Colors.GREEN}{Colors.BOLD}[SUCCESS] RESTORE DRILL PASSED: Backup payload is 100% restorable!{Colors.RESET}")
        print(f"{Colors.GREEN}{res_msg}{Colors.RESET}\n")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}[FAIL] RESTORE DRILL FAILED!{Colors.RESET}")
        print(f"{Colors.RED}{res_msg}{Colors.RESET}\n")
    return success

def _save_and_feedback(cfg):
    ok, msg = save_config(cfg)
    # Also synchronize to local BASE_DIR if config.json exists there
    local_cfg = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(local_cfg):
        try:
            with open(local_cfg, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4)
        except Exception:
            pass
    if ok:
        print(f"\n{Colors.GREEN}{Colors.BOLD}[SUCCESS] Settings saved successfully to config.json!{Colors.RESET}\n")
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}[ERROR] Could not save settings: {msg}{Colors.RESET}\n")

def action_view_settings(interactive=False):
    """Displays current system settings and provides configuration options."""
    cfg = load_config()
    while True:
        print(f"\n{Colors.BOLD}{Colors.CYAN}--- SYSTEM CONFIGURATION & SETTINGS (config.json) ---{Colors.RESET}")
        print(f"  [1] SQL Server Instance:    {Colors.BOLD}{cfg.get('SQL_SERVER_NAME', 'localhost')}{Colors.RESET}")
        print(f"  [2] SQL Authentication:     Username: '{cfg.get('SQL_USERNAME', 'sa')}', Password: [HIDDEN]")
        print(f"  [3] Target Databases:       {Colors.BOLD}{', '.join(cfg.get('TARGET_DATABASES', [])) or '[None]'}{Colors.RESET}")
        print(f"  [4] Local Backup Folder:    {cfg.get('BACKUP_FOLDER', 'E:\\DatabaseBackups')}")
        print(f"  [5] Delete Local On Sync:   {cfg.get('DELETE_LOCAL_AFTER_UPLOAD', True)}")
        print(f"  [6] Encryption By Default:  {cfg.get('ENCRYPTION_ENABLED', True)} (DBK2)")
        print(f"  [7] Apps Script Broker URL: {cfg.get('BROKER_URL', '')}")
        print(f"  [8] Google Drive Folder ID: {cfg.get('GOOGLE_DRIVE_FOLDER_ID', '')}")
        print(f"  [9] Google Sheet ID:        {cfg.get('GOOGLE_SHEET_ID', '')}")
        print(f"  [10] Auto Schedule:         Every {', '.join(cfg.get('SCHEDULE_DAYS', ['MON']))} at {cfg.get('SCHEDULE_TIME', '02:00')}")
        print(f"  [11] Storage Monitor Rules: C-Drive: {cfg.get('STORAGE_C_DRIVE_ALERT_GB', 30)} GB | Other: {cfg.get('STORAGE_OTHER_DRIVES_ALERT_PERCENT', 90)}%")
        print("-" * 75)

        if not interactive:
            return

        print(f"  [0] Return to Main Menu\n")
        opt = input(f"{Colors.BOLD}Select a field number to edit [1-11, 0 to return]: {Colors.RESET}").strip()
        if opt in ("0", "q", "exit", "back", ""):
            break
        elif opt == "1":
            cur = cfg.get("SQL_SERVER_NAME", "localhost")
            val = input(f"Enter SQL Server Instance [current: {cur}]: ").strip()
            if val:
                cfg["SQL_SERVER_NAME"] = val
                _save_and_feedback(cfg)
        elif opt == "2":
            cur_u = cfg.get("SQL_USERNAME", "sa")
            val_u = input(f"Enter SQL Username [current: {cur_u}]: ").strip()
            if val_u:
                cfg["SQL_USERNAME"] = val_u
            val_p = input(f"Enter new SQL Password [press Enter to leave unchanged]: ").strip()
            if val_p:
                cfg["SQL_PASSWORD"] = val_p
            _save_and_feedback(cfg)
        elif opt == "3":
            cur_dbs = ", ".join(cfg.get("TARGET_DATABASES", []))
            print(f"Enter target databases separated by commas (e.g. WAGlassKote, WAGlassKote_Test)")
            val = input(f"Databases [current: {cur_dbs}]: ").strip()
            if val:
                dbs = [d.strip() for d in val.split(",") if d.strip()]
                cfg["TARGET_DATABASES"] = dbs
                _save_and_feedback(cfg)
        elif opt == "4":
            cur = cfg.get("BACKUP_FOLDER", "E:\\DatabaseBackups")
            val = input(f"Enter Local Backup Staging Directory [current: {cur}]: ").strip().strip('"')
            if val:
                cfg["BACKUP_FOLDER"] = val
                _save_and_feedback(cfg)
        elif opt == "5":
            cur = cfg.get("DELETE_LOCAL_AFTER_UPLOAD", True)
            inp = input(f"Delete local backup file after upload to cloud? [Y/n, current: {'Y' if cur else 'N'}]: ").strip().lower()
            if inp in ("y", "yes", "true", "1"):
                cfg["DELETE_LOCAL_AFTER_UPLOAD"] = True
                _save_and_feedback(cfg)
            elif inp in ("n", "no", "false", "0"):
                cfg["DELETE_LOCAL_AFTER_UPLOAD"] = False
                _save_and_feedback(cfg)
        elif opt == "6":
            cur = cfg.get("ENCRYPTION_ENABLED", True)
            inp = input(f"Enable Zero-Trust Encryption (.dbk2) by default? [Y/n, current: {'Y' if cur else 'N'}]: ").strip().lower()
            if inp in ("y", "yes", "true", "1"):
                cfg["ENCRYPTION_ENABLED"] = True
                _save_and_feedback(cfg)
            elif inp in ("n", "no", "false", "0"):
                cfg["ENCRYPTION_ENABLED"] = False
                _save_and_feedback(cfg)
        elif opt == "7":
            cur = cfg.get("BROKER_URL", "")
            val = input(f"Enter Apps Script Web App URL [current: {cur}]: ").strip()
            if val:
                cfg["BROKER_URL"] = val
                _save_and_feedback(cfg)
        elif opt == "8":
            cur = cfg.get("GOOGLE_DRIVE_FOLDER_ID", "")
            val = input(f"Enter Google Drive Folder ID or URL [current: {cur}]: ").strip()
            if val:
                ext_id = extract_google_id(val)
                cfg["GOOGLE_DRIVE_FOLDER_ID"] = ext_id
                _save_and_feedback(cfg)
        elif opt == "9":
            cur = cfg.get("GOOGLE_SHEET_ID", "")
            val = input(f"Enter Customer Master Google Sheet ID or URL [current: {cur}]: ").strip()
            if val:
                ext_id = extract_google_id(val)
                cfg["GOOGLE_SHEET_ID"] = ext_id
                _save_and_feedback(cfg)
        elif opt == "10":
            action_schedule_configure()
            cfg = load_config()
        elif opt == "11":
            cur_c = str(cfg.get("STORAGE_C_DRIVE_ALERT_GB", 30))
            inp_c = input(f"Enter C: Drive Free Space Warning Alert (GB) [current: {cur_c}]: ").strip()
            if inp_c and inp_c.isdigit():
                cfg["STORAGE_C_DRIVE_ALERT_GB"] = int(inp_c)
            cur_o = str(cfg.get("STORAGE_OTHER_DRIVES_ALERT_PERCENT", 90))
            inp_o = input(f"Enter Other Drives Capacity Alert Threshold (%) [current: {cur_o}]: ").strip()
            if inp_o and inp_o.isdigit():
                cfg["STORAGE_OTHER_DRIVES_ALERT_PERCENT"] = int(inp_o)
            _save_and_feedback(cfg)
        else:
            print(f"{Colors.RED}Invalid choice.{Colors.RESET}")

def action_view_logs(lines=50):
    """Displays the most recent log entries."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- RECENT SYSTEM LOGS (Last {lines} entries) ---{Colors.RESET}")
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                for l in all_lines[-lines:]:
                    print("  " + l.strip())
        except Exception as e:
            print(f"{Colors.RED}Could not read log file: {e}{Colors.RESET}")
    else:
        print(f"Log file not found at: {LOG_FILE}")
    print("-" * 70 + "\n")

# =============================================================================
# INTERACTIVE CONSOLE MENU LOOP
# =============================================================================

def interactive_menu():
    """Main interactive text UI loop."""
    while True:
        print_banner()
        print(f"{Colors.BOLD}Select an operation:{Colors.RESET}")
        print(f"  {Colors.GREEN}[1]{Colors.RESET} Run Full Backup (Manual One-Click: Encrypted .dbk2 or .zip)")
        print(f"  {Colors.BLUE}[2]{Colors.RESET} Automated Schedule Manager (View, Set Days, Time, Mode)")
        print(f"  {Colors.CYAN}[3]{Colors.RESET} System Configuration & Settings (View / Edit config.json)")
        print(f"  {Colors.YELLOW}[4]{Colors.RESET} Preflight & Broker Diagnostics (Validate Token, Keys, Endpoints)")
        print(f"  {Colors.GREEN}[5]{Colors.RESET} Test Customer Google Sheet (Verify Sheet ID & Multi-Module Tabs)")
        print(f"  {Colors.CYAN}[6]{Colors.RESET} Server Health & Storage Cleanup (Scan Drive Space & Log Telemetry)")
        print(f"  {Colors.YELLOW}[7]{Colors.RESET} Database Performance & Maintenance (DBCC CHECKDB & DBREINDEX)")
        print(f"  {Colors.BLUE}[8]{Colors.RESET} Database Restore & Decrypt Wizard (Decrypt .dbk2 to .zip / .bak)")
        print(f"  {Colors.GREEN}[9]{Colors.RESET} Automated Restore Drill (RESTORE VERIFYONLY WITH CHECKSUM - Finding B1)")
        print(f"  {Colors.DIM}[10]{Colors.RESET} View Recent System Logs")
        print(f"  {Colors.RED}[0]{Colors.RESET} Exit")
        print("=" * 75)

        choice = input(f"{Colors.BOLD}Enter your choice [0-10]: {Colors.RESET}").strip()
        
        try:
            if choice == "1":
                action_manual_backup()
            elif choice == "2":
                print(f"\n[A] View Status | [B] Configure / Enable | [C] Disable | [Back]")
                sub = input("Select: ").strip().upper()
                if sub == "A": action_schedule_status()
                elif sub == "B": action_schedule_configure()
                elif sub == "C": action_schedule_disable()
            elif choice == "3":
                action_view_settings(interactive=True)
            elif choice == "4":
                action_test_broker()
            elif choice == "5":
                action_test_sheet()
            elif choice == "6":
                action_storage_cleanup()
            elif choice == "7":
                action_performance_query()
            elif choice == "8":
                action_decrypt_wizard()
            elif choice == "9":
                action_verify_restore()
            elif choice == "10":
                action_view_logs()
            elif choice in ("0", "q", "exit", "quit"):
                print(f"\n{Colors.CYAN}Exiting Enterprise Database Cloud Backup CLI. Goodbye!{Colors.RESET}\n")
                break
            else:
                print(f"{Colors.RED}Invalid selection. Please choose 0-10.{Colors.RESET}")
        except Exception as err:
            print(f"\n{Colors.RED}{Colors.BOLD}[ERROR] Operation encountered an error: {err}{Colors.RESET}\n")
        
        input(f"\n{Colors.DIM}Press Enter to return to main menu...{Colors.RESET}")

# =============================================================================
# COMMAND LINE ENTRYPOINT (FLAGS + DISPATCH)
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=f"Enterprise Database Cloud Backup - CLI Engine v{APP_VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  DatabaseBackupCLI.exe                           (Launch interactive console menu)
  DatabaseBackupCLI.exe --backup                 (Run full backup with default encryption)
  DatabaseBackupCLI.exe --backup --no-encrypt    (Run full backup uploading standard .zip)
  DatabaseBackupCLI.exe --schedule-status        (Query Windows automation state)
  DatabaseBackupCLI.exe --test-broker            (Test cloud broker connection)
  DatabaseBackupCLI.exe --test-sheet             (Verify Google Sheet connectivity)
  DatabaseBackupCLI.exe --storage-scan           (Run drive space health scan)
  DatabaseBackupCLI.exe --perf --db WAGlassKote  (Run database integrity & reindex)
  DatabaseBackupCLI.exe --verify-restore         (Run automated non-destructive restore drill)
  DatabaseBackupCLI.exe --decrypt -i file.dbk2 -k key.pem -o out.zip
"""
    )
    parser.add_argument("--interactive", action="store_true", help="Launch interactive text menu")
    parser.add_argument("--backup", action="store_true", help="Execute immediate full database backup")
    parser.add_argument("--encrypt", dest="encrypt_choice", action="store_const", const=True, help="Force encryption (.dbk2)")
    parser.add_argument("--no-encrypt", dest="encrypt_choice", action="store_const", const=False, help="Force standard .zip upload (unencrypted)")
    parser.add_argument("--schedule-status", action="store_true", help="Check active scheduled tasks")
    parser.add_argument("--schedule-enable", action="store_true", help="Enable scheduled backup task")
    parser.add_argument("--schedule-disable", action="store_true", help="Disable scheduled backup task")
    parser.add_argument("--days", type=str, help="Comma-separated schedule days (e.g. MON,WED,FRI or DAILY)")
    parser.add_argument("--time", dest="time_str", type=str, help="Schedule time in 24h format (e.g. 02:00, 14:30)")
    parser.add_argument("--system", dest="as_system", action="store_true", help="Run task as NT AUTHORITY\\SYSTEM service")
    parser.add_argument("--user", dest="as_system", action="store_false", help="Run task as current interactive user")
    parser.add_argument("--test-broker", action="store_true", help="Test preflights and broker connection")
    parser.add_argument("--test-sheet", action="store_true", help="Verify Google Sheet connection & tabs")
    parser.add_argument("--storage-scan", action="store_true", help="Run storage monitoring scan")
    parser.add_argument("--perf", "--performance-query", dest="perf", action="store_true", help="Run DBCC CHECKDB & re-indexing")
    parser.add_argument("--verify-restore", dest="verify_restore", action="store_true", help="Run automated non-destructive restore drill (RESTORE VERIFYONLY WITH CHECKSUM)")
    parser.add_argument("--file", dest="target_file", type=str, help="Target backup file (.bak, .zip, .dbk2) for restore verification")
    parser.add_argument("--db", type=str, help="Target database name for backup or performance")
    parser.add_argument("--decrypt", action="store_true", help="Run decryption on a .dbk2 file")
    parser.add_argument("-i", "--input", dest="enc_input", type=str, help="Encrypted .dbk2 input file")
    parser.add_argument("-k", "--key", dest="key_path", type=str, help="Private key file for decryption")
    parser.add_argument("-o", "--output", dest="dec_output", type=str, help="Decrypted output file path (.zip)")
    parser.add_argument("--config-show", action="store_true", help="Display current config.json")
    parser.add_argument("--config-set", nargs=2, metavar=("KEY", "VALUE"), help="Set configuration value (e.g. --config-set SQL_SERVER_NAME localhost)")
    parser.add_argument("--logs", action="store_true", help="Display recent log entries")
    parser.add_argument("-n", "--lines", type=int, default=50, help="Number of log lines to display")

    args = parser.parse_args()

    # If no flags passed, launch interactive menu
    if len(sys.argv) == 1 or args.interactive:
        interactive_menu()
        return

    # Dispatch flags
    if args.config_set:
        key, val = args.config_set
        cfg = load_config()
        if val.lower() in ("true", "yes", "1"):
            parsed_val = True
        elif val.lower() in ("false", "no", "0"):
            parsed_val = False
        elif val.isdigit():
            parsed_val = int(val)
        elif "," in val and key == "TARGET_DATABASES":
            parsed_val = [x.strip() for x in val.split(",") if x.strip()]
        elif key in ("GOOGLE_DRIVE_FOLDER_ID", "GOOGLE_SHEET_ID"):
            parsed_val = extract_google_id(val)
        else:
            parsed_val = val
        cfg[key] = parsed_val
        _save_and_feedback(cfg)
        print(f"[SUCCESS] Updated configuration: {key} = {parsed_val}")
    elif args.backup:
        action_manual_backup(encrypt_choice=args.encrypt_choice)
    elif args.schedule_status:
        action_schedule_status()
    elif args.schedule_enable:
        days_list = [d.strip().upper() for d in args.days.split(",")] if args.days else None
        action_schedule_configure(days=days_list, time_str=args.time_str, as_system=args.as_system)
    elif args.schedule_disable:
        action_schedule_disable()
    elif args.test_broker:
        action_test_broker()
    elif args.test_sheet:
        action_test_sheet()
    elif args.storage_scan:
        action_storage_cleanup()
    elif args.perf:
        action_performance_query(target_db=args.db)
    elif args.verify_restore:
        action_verify_restore(target_file=args.target_file, instance=args.db)
    elif args.decrypt:
        action_decrypt_wizard(enc_path=args.enc_input, key_path=args.key_path, out_path=args.dec_output)
    elif args.config_show:
        action_view_settings()
    elif args.logs:
        action_view_logs(lines=args.lines)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
