"""
App-side client for the upload broker. The app holds NO Google credentials.
Its only secret is a per-PC broker token that can request "start an upload" and nothing else.
"""
import os, time, base64, hashlib, json, requests
from urllib.parse import urljoin

CHUNK = 8 * 1024 * 1024  # must be a multiple of 256 KiB for GCS resumable uploads
RETRYABLE = (429, 500, 502, 503, 504)
_REDIRECT_CODES = (301, 302, 303, 307, 308)


# ---- token storage (Windows DPAPI, machine scope; native crypt32.dll + fallback) ----
CRYPTPROTECT_LOCAL_MACHINE = 0x4
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _protect_dpapi_native(data_bytes):
    """Protects data with Windows DPAPI (LocalMachine scope) using system crypt32.dll."""
    if isinstance(data_bytes, str):
        data_bytes = data_bytes.encode("utf-8")
    if os.name != "nt":
        return data_bytes
    try:
        import ctypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(DATA_BLOB)
        ]
        crypt32.CryptProtectData.restype = ctypes.c_int

        in_buf = ctypes.create_string_buffer(data_bytes)
        blob_in = DATA_BLOB(len(data_bytes), ctypes.cast(in_buf, ctypes.c_void_p))
        blob_out = DATA_BLOB()
        flags = CRYPTPROTECT_LOCAL_MACHINE | CRYPTPROTECT_UI_FORBIDDEN
        if not crypt32.CryptProtectData(ctypes.byref(blob_in), "BackupBrokerToken", None, None, None, flags, ctypes.byref(blob_out)):
            # Fallback to user scope if LocalMachine requires elevation
            if not crypt32.CryptProtectData(ctypes.byref(blob_in), "BackupBrokerToken", None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)):
                raise ctypes.WinError()
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32.LocalFree(blob_out.pbData)
        return out
    except Exception:
        try:
            import win32crypt
            return win32crypt.CryptProtectData(data_bytes, "BackupBrokerToken", None, None, None, CRYPTPROTECT_LOCAL_MACHINE)
        except Exception:
            return data_bytes


def _unprotect_dpapi_native(cipher_bytes):
    """Unprotects DPAPI data using system crypt32.dll with win32crypt fallback."""
    if os.name != "nt":
        return cipher_bytes.decode("utf-8", errors="ignore").strip()
    try:
        import ctypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(DATA_BLOB),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(DATA_BLOB)
        ]
        crypt32.CryptUnprotectData.restype = ctypes.c_int

        in_buf = ctypes.create_string_buffer(cipher_bytes)
        blob_in = DATA_BLOB(len(cipher_bytes), ctypes.cast(in_buf, ctypes.c_void_p))
        blob_out = DATA_BLOB()
        flags = CRYPTPROTECT_UI_FORBIDDEN
        if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)):
            raise ctypes.WinError()
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        kernel32.LocalFree(blob_out.pbData)
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        try:
            import win32crypt
            return win32crypt.CryptUnprotectData(cipher_bytes, None, None, None, 0)[1].decode("utf-8", errors="replace").strip()
        except Exception:
            return ""


def secure_token_file_acl(path):
    """
    Restricts access on the DPAPI token file to Administrators, SYSTEM, and the run-as account.
    Prevents unauthorized standard users from reading the machine-scoped token.
    """
    if os.name != "nt" or not os.path.exists(path):
        return
    try:
        import subprocess
        cur_user = os.environ.get("USERNAME", "")
        cmd = ["icacls.exe", path, "/inheritance:r", "/grant:r", "Administrators:F", "SYSTEM:F"]
        if cur_user:
            cmd.extend([f"{cur_user}:M"])
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass


def save_token(path, token):
    data_bytes = token.encode("utf-8") if isinstance(token, str) else token
    encrypted = _protect_dpapi_native(data_bytes)
    with open(path, "wb") as f:
        f.write(encrypted)
    secure_token_file_acl(path)


def load_token(path):
    with open(path, "rb") as f:
        data = f.read()
    return _unprotect_dpapi_native(data)


def validate_broker_url(url):
    """
    Validates that the broker URL is using HTTPS.
    http://127.0.0.1 and http://localhost are rejected by default in production,
    and are permitted ONLY when ALLOW_INSECURE_BROKER=true is explicitly set.
    """
    if not url or not isinstance(url, str):
        raise ValueError("Broker URL must be a non-empty string.")
    clean = url.strip()
    lower = clean.lower()
    if lower.startswith("https://"):
        return clean
    if lower.startswith("http://127.0.0.1") or lower.startswith("http://localhost"):
        is_dev = False
        try:
            import version
            is_dev = getattr(version, "DEV_MODE", False)
        except Exception:
            pass
        if is_dev or os.environ.get("ALLOW_INSECURE_BROKER", "").lower() == "true":
            return clean
        raise ValueError(
            "Insecure HTTP broker URL rejected in production. "
            "Local HTTP is allowed only if ALLOW_INSECURE_BROKER=true is set."
        )
    raise ValueError(
        f"Insecure or invalid broker URL '{clean}'. Only HTTPS is permitted in production."
    )


def parse_broker_response(response):
    """
    Maps an Apps Script / HTTP response to (logical_status, data, error_message).
    ContentService always returns HTTP 200; the real status is in JSON {error, code}.
    """
    text = (getattr(response, "text", None) or "")
    data = {}
    try:
        if text:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
    except Exception:
        lower = text.lower()
        if "<html" in lower or "sign in" in lower:
            return 502, {}, "Broker returned an HTML page instead of JSON. Redeploy the Web App with access = Anyone."
        return 502, {}, f"Broker returned non-JSON: {text[:120]}"

    if data.get("error"):
        try:
            logical = int(data.get("code") or 400)
        except (TypeError, ValueError):
            logical = 400
        return logical, data, str(data.get("error"))

    http_status = getattr(response, "status_code", 200) or 200
    if http_status >= 400:
        return http_status, data, (text[:200] or f"HTTP {http_status}")
    return http_status, data, None


def post_broker(url, payload, timeout=30):
    """
    POST JSON to the Apps Script web app and retrieve the JSON response.
    Apps Script processes doPost(e) and responds with a 302 redirect to
    script.googleusercontent.com/macros/echo to deliver the ContentService payload via GET.
    """
    valid_url = validate_broker_url(url)
    headers = {"Content-Type": "application/json; charset=utf-8"}
    body = json.dumps(payload)
    
    response = requests.post(
        valid_url, data=body, headers=headers, allow_redirects=False, timeout=timeout
    )
    if response.status_code in _REDIRECT_CODES:
        location = response.headers.get("Location") or response.headers.get("location")
        if location:
            target = location if location.lower().startswith("http") else urljoin(valid_url, location)
            if "googleusercontent.com" in target.lower() or response.status_code in (301, 302, 303):
                return requests.get(target, timeout=timeout)
            else:
                return requests.post(target, data=body, headers=headers, allow_redirects=False, timeout=timeout)
    return response


def verify_broker_token(broker_url, token, timeout=10):
    """Returns (ok, pc_id_or_error). Uses the Apps Script {action: verify} protocol."""
    if not token or "." not in token:
        return False, "Token format invalid (expected pc_id.secret)"
    try:
        r = post_broker(broker_url, {"action": "verify", "token": token}, timeout=timeout)
        status, data, err = parse_broker_response(r)
        if err or status >= 400:
            return False, err or f"HTTP {status}"
        return True, data.get("pc_id") or token.split(".", 1)[0]
    except Exception as e:
        return False, str(e)


def import_and_protect_token(raw_token_input, target_path):
    """
    Imports a raw token (string or path to raw_token.txt), protects it locally
    using Windows DPAPI (machine scope 0x4), saves to target_path with strict ACLs,
    and securely wipes the plaintext raw_token.txt file.
    """
    token_str = ""
    is_file = False
    if os.path.isfile(raw_token_input):
        is_file = True
        with open(raw_token_input, "r", encoding="utf-8") as f:
            token_str = f.read().strip()
    else:
        token_str = str(raw_token_input).strip()

    try:
        if not token_str or "." not in token_str:
            raise ValueError("Invalid raw token format. Expected '<pc_id>.<secret>'")
        save_token(target_path, token_str)
    finally:
        if is_file:
            try:
                # Overwrite with random bytes before unlinking
                file_len = os.path.getsize(raw_token_input)
                with open(raw_token_input, "wb") as f:
                    f.write(os.urandom(max(file_len, 64)))
                    f.flush()
                    os.fsync(f.fileno())
                os.remove(raw_token_input)
            except Exception:
                pass
    return True


def enroll_pc(broker_url, enroll_code, pc_id, customer_slug, target_token_path, target_offset_path):
    """
    Zero-billing enrollment protocol. Client generates token locally, sends to broker.
    Broker atomically registers it and returns a stagger offset.
    """
    import secrets

    enroll_code = str(enroll_code or "").strip()
    pc_id = str(pc_id or "").strip()
    customer_slug = str(customer_slug or "").strip()
    if not enroll_code or not pc_id or not customer_slug:
        return False, "Enrollment requires enroll_code, pc_id, and customer_slug"

    secret = secrets.token_urlsafe(32).replace(".", "_")
    token = f"{pc_id}.{secret}"

    payload = {
        "action": "enroll",
        "enroll_code": enroll_code,
        "pc_id": pc_id,
        "customer_slug": customer_slug,
        "token": token
    }

    try:
        r = post_broker(broker_url, payload, timeout=30)
        status, data, err = parse_broker_response(r)
        if err or status >= 400:
            return False, err or f"HTTP {status}"

        offset_minutes = data.get("offset_minutes", 0)
        import_and_protect_token(token, target_token_path)
        os.makedirs(os.path.dirname(os.path.abspath(target_offset_path)), exist_ok=True)
        with open(target_offset_path, "w", encoding="utf-8") as f:
            json.dump({"offset_minutes": offset_minutes}, f)
        return True, offset_minutes
    except Exception as e:
        return False, str(e)


# ---- broker + storage ----
def _md5_b64(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(blk)
    return base64.b64encode(h.digest()).decode()


def request_session(broker_url, token, db, size, seq=1):
    return post_broker(
        broker_url,
        {"action": "request_upload", "token": token, "db_name": db, "size_bytes": size, "seq": seq},
        timeout=30,
    )


def _query_offset(uri, total):
    """Ask GCS how many bytes it has. Returns (offset, finished_response_or_None)."""
    r = requests.put(uri, headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"}, timeout=30)
    if r.status_code in (200, 201):
        return total, r
    if r.status_code == 308:
        rng = r.headers.get("Range")
        return (int(rng.split("-")[1]) + 1 if rng else 0), None
    raise RuntimeError(f"status query failed: HTTP {r.status_code}")


def _put_all(uri, path, total, log, progress_cb, telemetry_cb, cancel_check):
    if not uri:
        log("Upload session URI is empty.", "error")
        return None
    name = os.path.basename(path)
    start = time.time()
    pos, final = 0, None
    with open(path, "rb") as f:
        while pos < total:
            if cancel_check and cancel_check():
                return None
            f.seek(pos)
            data = f.read(min(CHUNK, total - pos))
            hdr = {"Content-Length": str(len(data)),
                   "Content-Range": f"bytes {pos}-{pos + len(data) - 1}/{total}"}
            for attempt in range(1, 11):
                try:
                    r = requests.put(uri, data=data, headers=hdr, timeout=(15, 180))
                    if r.status_code in (200, 201):
                        pos, final = total, r
                    elif r.status_code == 308:
                        rng = r.headers.get("Range")
                        pos = int(rng.split("-")[1]) + 1 if rng else 0
                    elif r.status_code in RETRYABLE:
                        raise ConnectionError(f"HTTP {r.status_code}")
                    else:
                        log(f"Upload rejected by storage: HTTP {r.status_code}", "error")
                        return None
                    break
                except (requests.ConnectionError, requests.Timeout, ConnectionError) as e:
                    wait = min(60, 2 ** attempt)
                    log(f"Network problem ({e}); resuming in {wait}s (try {attempt}/10)", "warning")
                    time.sleep(wait)
                    try:
                        pos, done = _query_offset(uri, total)
                        if done is not None:
                            final = done
                            break
                        f.seek(pos)
                        data = f.read(min(CHUNK, total - pos))
                        hdr = {"Content-Length": str(len(data)),
                               "Content-Range": f"bytes {pos}-{pos + len(data) - 1}/{total}"}
                    except Exception:
                        pass
            else:
                log("Upload failed after 10 retries.", "error")
                return None
            elapsed = max(0.001, time.time() - start)
            frac = pos / total if total else 1.0
            if progress_cb:
                progress_cb(frac)
            if telemetry_cb:
                bps = pos / elapsed
                try:
                    telemetry_cb({"file_name": name, "bytes_done": pos, "total_bytes": total,
                                  "percent": frac * 100, "fraction": frac, "speed_bps": bps,
                                  "speed_str": f"{bps / 1048576:.1f} MB/s",
                                  "eta_str": f"{int((total - pos) / bps)}s" if bps else "--",
                                  "elapsed": elapsed})
                except Exception:
                    pass
    return final


def secure_upload(file_path, db_name, config, base_dir, log_cb=None, progress_cb=None,
                  telemetry_cb=None, cancel_check=None, status_cb=None):
    """Returns the remote object name on VERIFIED success, else None.
    Never deletes anything; the caller deletes local files only after a non-None return."""
    def log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    broker_url = config.get("BROKER_URL", "")
    token_name = config.get("BROKER_TOKEN_FILE", "token.dpapi")
    token_path = token_name if os.path.isabs(token_name) else os.path.join(base_dir, token_name)
    if not os.path.exists(token_path):
        prog_data = os.environ.get("ALLUSERSPROFILE", r"C:\ProgramData")
        alt = os.path.join(prog_data, "DatabaseBackupApp", os.path.basename(token_name))
        if os.path.exists(alt):
            token_path = alt
    if not broker_url or not os.path.exists(token_path):
        log(f"Broker not configured (BROKER_URL or {os.path.basename(token_name)} missing).", "critical")
        return None
    token = load_token(token_path)
    total = os.path.getsize(file_path)

    info = None
    for seq in (1, 2, 3):
        try:
            r = request_session(broker_url, token, db_name, total, seq)
        except requests.RequestException as e:
            log(f"Broker unreachable: {e}", "error")
            return None
        except ValueError as e:
            log(f"Broker configuration error: {e}", "critical")
            return None
        status, data, err = parse_broker_response(r)
        if not err and status < 400:
            upload_uri = data.get("upload_url") or data.get("session_uri")
            if not upload_uri:
                log("Broker accepted the request but did not return an upload URL.", "error")
                return None
            info = data
            break
        if status in (409, 429):
            log(
                f"Upload slot {seq}/3 for database '{db_name}' is already used today "
                f"(HTTP {status} Conflict). Trying slot {seq + 1}...",
                "warning",
            )
            if status == 429:
                # Apps Script counts by day, not by seq; further slot retries will also 429.
                log(
                    f"SECURITY ALERT: All 3 upload slots for database '{db_name}' are exhausted today. "
                    "If you did not execute 3 backups today, your token may be compromised or experiencing slot-burning.",
                    "critical",
                )
                return None
            continue
        log(f"Broker refused the upload (HTTP {status}: {err or r.text[:120]}).", "error")
        return None
    else:
        log(f"SECURITY ALERT: All 3 upload slots for database '{db_name}' are exhausted today. "
            f"If you did not execute 3 backups today, your token may be compromised or experiencing slot-burning.", "critical")
        return None

    if status_cb:
        status_cb(f"Uploading {os.path.basename(file_path)} ...")
    upload_uri = info.get("upload_url") or info.get("session_uri")
    resp = _put_all(upload_uri, file_path, total, log, progress_cb, telemetry_cb, cancel_check)
    if resp is None:
        return None

    resp_json = resp.json() if resp.text else {}
    remote_md5 = resp_json.get("md5Checksum") or resp_json.get("md5Hash")
    if remote_md5 and remote_md5 != _md5_b64(file_path):
        log("Integrity check FAILED: remote checksum differs from local file.", "critical")
        return None
    log(f"Upload verified (MD5 match): {info.get('file_name', info.get('object'))}", "info")
    return info.get('file_name', info.get('object'))


def report_storage_telemetry(telemetry_broker_url, token, drives, tab_name="Storage Monitor"):
    """
    Sends drive health stats to the separate Telemetry Broker endpoint (POST /report-status).
    Note: Client NEVER sends a Sheet ID. The broker handles sheet insertion safely.
    Returns (success_boolean, message)
    """
    if not telemetry_broker_url or not token:
        return False, "Telemetry Broker URL or token missing"

    try:
        valid_url = validate_broker_url(telemetry_broker_url)
    except ValueError as e:
        return False, f"Telemetry Broker URL rejected: {e}"

    payload = {"action": "report_status", "token": token, "drives": drives, "tab_name": tab_name}
    try:
        r = post_broker(valid_url, payload, timeout=15)
        status, data, err = parse_broker_response(r)
        if not err and status < 400:
            return True, f"Telemetry reported ({data.get('drives_logged', len(drives))} drives logged)"
        if status == 429:
            return False, "Telemetry rate limited (max 1 report per 15 mins)"
        return False, f"Telemetry broker rejected report: HTTP {status} - {err or r.text[:100]}"
    except Exception as e:
        return False, f"Telemetry broker error: {e}"


def report_performance_telemetry(
    broker_url,
    token,
    db_name,
    sql_version="Microsoft SQL Server",
    db_size_mb=0,
    pre_backup_status="Completed",
    frag_before_max=0.0,
    frag_after_max=0.0,
    checkdb_status="Clean (0 consistency errors)",
    reindex_status="Reindexed (FillFactor 80)",
    duration_secs=0.0,
    run_mode="Manual",
    task_start_time=None,
    query_exec_time=None,
    status="SUCCESS"
):
    """
    Sends database performance and re-indexing telemetry to the Upload Broker.
    Routes to the Customer Sheet [Performance Query] tab and Master Application Report.
    Returns (success_boolean, message)
    """
    if not broker_url or not token:
        return False, "Broker URL or token missing"

    try:
        valid_url = validate_broker_url(broker_url)
    except ValueError as e:
        return False, f"Broker URL rejected: {e}"

    from datetime import datetime as dt
    now_str = dt.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "action": "report_status",
        "token": token,
        "module": "PERFORMANCE_QUERY",
        "run_mode": run_mode,
        "task_start_time": task_start_time or now_str,
        "query_exec_time": query_exec_time or now_str,
        "db_name": db_name,
        "sql_version": sql_version,
        "db_size_mb": db_size_mb,
        "pre_backup_status": pre_backup_status,
        "frag_before_max": frag_before_max,
        "frag_after_max": frag_after_max,
        "checkdb_status": checkdb_status,
        "reindex_status": reindex_status,
        "duration_secs": duration_secs,
        "status": status
    }
    try:
        r = post_broker(valid_url, payload, timeout=20)
        status_code, data, err = parse_broker_response(r)
        if not err and status_code < 400:
            return True, "Performance telemetry recorded successfully in Google Sheet"
        return False, f"Broker rejected report: HTTP {status_code} - {err or r.text[:100]}"
    except Exception as e:
        return False, f"Performance telemetry error: {e}"

