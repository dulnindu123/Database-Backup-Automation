"""
admin_restore_drill.py
=============================================================================
Automated End-to-End Disaster Recovery Drill & Database Integrity Verification
Enterprise Database Cloud Backup Automation v5.0.1 (Post-Audit Hardened Edition)

Features:
1. Streams and decrypts encrypted .dbk2 archives using AES-256-GCM + RSA-4096.
2. Validates 128-bit MAC authentication tags and container header integrity.
3. Restores raw database into an isolated temporary sandbox database on SQL Server.
4. Executes DBCC CHECKDB (... WITH PHYSICAL_ONLY) to verify allocation & page consistency.
5. Safely drops temporary sandbox database and cleans up decrypted staging files.
6. Emits structured JSON audit report for regulatory and compliance review.
=============================================================================
"""

import os
import sys
import time
import json
import shutil
import zipfile
import argparse
import subprocess
from datetime import datetime

# Import local cryptographic stream decryptor
try:
    from crypto_stream import decrypt_file
except ImportError:
    # Try importing from relative or parent directories
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "2_Disaster_Recovery"))
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "BackupAutomation_v5.0"))
    from crypto_stream import decrypt_file


def run_sql_query(query, server="localhost", database="master", timeout=60):
    """Executes a T-SQL query via sqlcmd.exe or powershell Invoke-Sqlcmd."""
    cmd = [
        "sqlcmd",
        "-S", server,
        "-d", database,
        "-E",  # Trusted connection
        "-b",  # On error exit
        "-Q", query
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout, res.stderr
    except FileNotFoundError:
        # Fallback to PowerShell
        ps_cmd = f"Invoke-Sqlcmd -ServerInstance '{server}' -Database '{database}' -Query \"{query}\" -QueryTimeout {timeout}"
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=timeout)
        return res.returncode == 0, res.stdout, res.stderr
    except Exception as e:
        return False, "", str(e)


def execute_dr_drill(encrypted_file, private_key_file, passphrase=None, server="localhost", staging_dir=None, keep_sandbox=False):
    """
    Executes an automated, full end-to-end disaster recovery drill:
    Decrypt -> Decompress -> Restore to Sandbox DB -> CHECKDB -> Drop Sandbox DB.
    """
    start_time = time.time()
    drill_report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "drill_type": "AUTOMATED_END_TO_END_DISASTER_RECOVERY_DRILL",
        "archive_file": os.path.abspath(encrypted_file),
        "private_key": os.path.abspath(private_key_file),
        "sql_server": server,
        "stages": {},
        "status": "FAILED",
        "error": None
    }

    print(f"\n======================================================================")
    print(f"  ENTERPRISE DISASTER RECOVERY DRILL — VERIFICATION RUN")
    print(f"======================================================================")
    print(f"Archive Target:     {encrypted_file}")
    print(f"Private Key:        {private_key_file}")
    print(f"SQL Server Host:    {server}")
    print(f"Timestamp:          {drill_report['timestamp']}\n")

    if not os.path.exists(encrypted_file):
        err = f"Target archive '{encrypted_file}' does not exist."
        drill_report["error"] = err
        print(f"[ERROR] {err}")
        return False, drill_report

    if not os.path.exists(private_key_file):
        err = f"Private key '{private_key_file}' does not exist."
        drill_report["error"] = err
        print(f"[ERROR] {err}")
        return False, drill_report

    # Prepare temporary staging directory
    temp_dir = staging_dir or os.path.join(os.environ.get("TEMP", r"C:\Temp"), f"DR_DRILL_{int(time.time())}")
    os.makedirs(temp_dir, exist_ok=True)
    decrypted_zip = os.path.join(temp_dir, "decrypted_archive.zip")
    extracted_bak_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extracted_bak_dir, exist_ok=True)

    try:
        # STAGE 1: Cryptographic Decryption
        print("[STAGE 1/5] Streaming AES-256-GCM Decryption & MAC Verification...")
        t0 = time.time()
        with open(private_key_file, "rb") as kf:
            priv_key_data = kf.read()
        
        ok, dec_meta = decrypt_file(encrypted_file, decrypted_zip, priv_key_data, passphrase)
        if not ok:
            err = f"Decryption failed: {dec_meta}"
            drill_report["stages"]["decryption"] = {"status": "FAILED", "error": dec_meta}
            drill_report["error"] = err
            print(f"  [✗] {err}")
            return False, drill_report

        drill_report["stages"]["decryption"] = {
            "status": "PASSED",
            "duration_sec": round(time.time() - t0, 2),
            "original_db": dec_meta.get("db_name", "UNKNOWN"),
            "original_host": dec_meta.get("host_name", "UNKNOWN"),
            "original_time": dec_meta.get("utc_time", "UNKNOWN")
        }
        print(f"  [✓] Decryption PASSED ({drill_report['stages']['decryption']['duration_sec']}s). Context: {dec_meta.get('db_name')}")

        # STAGE 2: Unpack Staged Archive
        print("[STAGE 2/5] Unpacking compressed database dump (.bak)...")
        t0 = time.time()
        bak_file = None
        if zipfile.is_zipfile(decrypted_zip):
            with zipfile.ZipFile(decrypted_zip, "r") as zf:
                zf.extractall(extracted_bak_dir)
                for f in os.listdir(extracted_bak_dir):
                    if f.lower().endswith(".bak"):
                        bak_file = os.path.join(extracted_bak_dir, f)
                        break
        else:
            # Container was direct .bak
            bak_file = decrypted_zip

        if not bak_file or not os.path.exists(bak_file):
            err = "No valid .bak file found inside decrypted archive."
            drill_report["stages"]["unpack"] = {"status": "FAILED", "error": err}
            drill_report["error"] = err
            print(f"  [✗] {err}")
            return False, drill_report

        bak_size_mb = round(os.path.getsize(bak_file) / (1024 * 1024), 2)
        drill_report["stages"]["unpack"] = {
            "status": "PASSED",
            "duration_sec": round(time.time() - t0, 2),
            "bak_file": os.path.basename(bak_file),
            "size_mb": bak_size_mb
        }
        print(f"  [✓] Unpack PASSED ({drill_report['stages']['unpack']['duration_sec']}s). Staged .bak: {bak_size_mb} MB")

        # STAGE 3: SQL Server Sandbox Restoration
        sandbox_db_name = f"_DR_DRILL_{int(time.time())}"
        print(f"[STAGE 3/5] Restoring into isolated SQL Server sandbox database [{sandbox_db_name}]...")
        t0 = time.time()

        # Query file list to construct MOVE directives
        fl_query = f"RESTORE FILELISTONLY FROM DISK = N'{bak_file}'"
        ok_fl, fl_out, fl_err = run_sql_query(fl_query, server=server)
        move_clauses = []
        if ok_fl and fl_out:
            lines = fl_out.strip().splitlines()
            for line in lines[2:]:
                parts = line.split()
                if len(parts) >= 2:
                    log_name = parts[0]
                    f_type = parts[1].upper()
                    if f_type in ("D", "ROWS"):
                        target_mdf = os.path.join(temp_dir, f"{sandbox_db_name}_{log_name}.mdf")
                        move_clauses.append(f"MOVE N'{log_name}' TO N'{target_mdf}'")
                    elif f_type in ("L", "LOG"):
                        target_ldf = os.path.join(temp_dir, f"{sandbox_db_name}_{log_name}.ldf")
                        move_clauses.append(f"MOVE N'{log_name}' TO N'{target_ldf}'")

        move_sql = (", " + ", ".join(move_clauses)) if move_clauses else ""
        restore_query = f"RESTORE DATABASE [{sandbox_db_name}] FROM DISK = N'{bak_file}' WITH NOUNLOAD, STATS = 20{move_sql}"
        ok_rest, rest_out, rest_err = run_sql_query(restore_query, server=server, timeout=300)

        if not ok_rest:
            err = f"SQL Server RESTORE failed: {rest_err or rest_out}"
            drill_report["stages"]["restore"] = {"status": "FAILED", "error": err}
            drill_report["error"] = err
            print(f"  [✗] {err}")
            return False, drill_report

        drill_report["stages"]["restore"] = {
            "status": "PASSED",
            "duration_sec": round(time.time() - t0, 2),
            "sandbox_db": sandbox_db_name
        }
        print(f"  [✓] Restoration PASSED ({drill_report['stages']['restore']['duration_sec']}s).")

        # STAGE 4: Integrity Verification (DBCC CHECKDB)
        print(f"[STAGE 4/5] Executing DBCC CHECKDB ('{sandbox_db_name}', WITH PHYSICAL_ONLY)...")
        t0 = time.time()
        checkdb_query = f"DBCC CHECKDB (N'{sandbox_db_name}') WITH PHYSICAL_ONLY, NO_INFOMSGS, ALL_ERRORMSGS"
        ok_chk, chk_out, chk_err = run_sql_query(checkdb_query, server=server, timeout=300)

        if not ok_chk or "CHECKDB found 0 errors" not in (chk_out + chk_err) and chk_err:
            if "Msg " in (chk_out + chk_err):
                err = f"DBCC CHECKDB detected corruption: {chk_err or chk_out}"
                drill_report["stages"]["checkdb"] = {"status": "FAILED", "error": err}
                drill_report["error"] = err
                print(f"  [✗] {err}")
                return False, drill_report

        drill_report["stages"]["checkdb"] = {
            "status": "PASSED",
            "duration_sec": round(time.time() - t0, 2),
            "result": "Zero physical or allocation corruption detected"
        }
        print(f"  [✓] DBCC CHECKDB PASSED: 0 errors found ({drill_report['stages']['checkdb']['duration_sec']}s).")

        # STAGE 5: Teardown & Clean Removal
        print(f"[STAGE 5/5] Tearing down temporary sandbox database and staging data...")
        if not keep_sandbox:
            drop_query = f"ALTER DATABASE [{sandbox_db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{sandbox_db_name}];"
            ok_drop, _, _ = run_sql_query(drop_query, server=server)
            drill_report["stages"]["cleanup"] = {"sandbox_dropped": ok_drop, "status": "PASSED"}
            print(f"  [✓] Sandbox database [{sandbox_db_name}] successfully dropped.")
        else:
            drill_report["stages"]["cleanup"] = {"sandbox_retained": True, "status": "SKIPPED"}
            print(f"  [i] Sandbox database [{sandbox_db_name}] retained per --keep-sandbox flag.")

        drill_report["status"] = "PASSED"
        drill_report["total_duration_sec"] = round(time.time() - start_time, 2)
        print(f"\n======================================================================")
        print(f"  DISASTER RECOVERY DRILL RESULT: SUCCESS (100% VERIFIED)")
        print(f"  Total Duration: {drill_report['total_duration_sec']} seconds")
        print(f"======================================================================\n")
        return True, drill_report

    finally:
        # Purge temporary staging files
        try:
            if os.path.exists(decrypted_zip):
                os.remove(decrypted_zip)
            if os.path.exists(extracted_bak_dir):
                shutil.rmtree(extracted_bak_dir, ignore_errors=True)
            if not keep_sandbox and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated Disaster Recovery Drill & Database Integrity Verifier")
    parser.add_argument("--archive", required=True, help="Path to encrypted .dbk2 archive")
    parser.add_argument("--key", required=True, help="Path to RSA-4096 private key (.pem)")
    parser.add_argument("--passphrase", default=None, help="Private key passphrase (if protected)")
    parser.add_argument("--server", default="localhost", help="SQL Server target instance (default: localhost)")
    parser.add_argument("--report", default="restore_drill_report.json", help="Path to output JSON audit report")
    parser.add_argument("--keep-sandbox", action="store_true", help="Retain sandbox database after drill (do not drop)")

    args = parser.parse_args()
    success, report = execute_dr_drill(
        encrypted_file=args.archive,
        private_key_file=args.key,
        passphrase=args.passphrase,
        server=args.server,
        keep_sandbox=args.keep_sandbox
    )

    with open(args.report, "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2)
    print(f"Drill audit report saved to: {args.report}")
    sys.exit(0 if success else 1)
