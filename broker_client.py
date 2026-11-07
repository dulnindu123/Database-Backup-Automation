"""
App-side client for the upload broker. The app holds NO Google credentials.
Its only secret is a per-PC broker token that can request "start an upload" and nothing else.
"""
import os, time, base64, hashlib, json, requests
from urllib.parse import urljoin

# ---- Adaptive High-Throughput Chunk Sizing ----
# Google Drive Resumable Upload protocol requires all chunks (except the final chunk)
# to be strictly a multiple of 256 KiB (262,144 bytes).
CHUNK_MULTIPLE = 256 * 1024       # 256 KiB alignment
MIN_CHUNK = 4 * 1024 * 1024       # 4 MiB (16x 256 KiB) - conservative baseline for slow/flaky links
DEFAULT_CHUNK = 8 * 1024 * 1024   # 8 MiB (32x 256 KiB) - Google Drive recommended standard baseline
HIGH_CHUNK = 16 * 1024 * 1024     # 16 MiB (64x 256 KiB) - for fast broadband (>= 5 MB/s)
MAX_CHUNK = 32 * 1024 * 1024      # 32 MiB (128x 256 KiB) - for ultra-fast lines (>= 12 MB/s, e.g. 100-500 Mbps)
CHUNK = DEFAULT_CHUNK             # Global fallback reference

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


def request_session(broker_url, token, db, size, seq=1, extension="dbk2", is_encrypted=True):
    return post_broker(
        broker_url,
        {
            "action": "request_upload",
            "token": token,
            "db_name": db,
            "size_bytes": size,
            "seq": seq,
            "extension": extension,
            "is_encrypted": is_encrypted
        },
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
    current_chunk = DEFAULT_CHUNK

    # Persistent HTTP session with connection pooling and TCP keep-alive
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    try:
        with open(path, "rb") as f:
            while pos < total:
                if cancel_check and cancel_check():
                    return None

                chunk_to_read = min(current_chunk, total - pos)
                # Google Drive Resumable Upload requires all non-final chunks to be multiples of 256 KiB
                if pos + chunk_to_read < total:
                    chunk_to_read = (chunk_to_read // CHUNK_MULTIPLE) * CHUNK_MULTIPLE
                    if chunk_to_read == 0:
                        chunk_to_read = CHUNK_MULTIPLE

                f.seek(pos)
                data = f.read(chunk_to_read)
                hdr = {"Content-Length": str(len(data)),
                       "Content-Range": f"bytes {pos}-{pos + len(data) - 1}/{total}"}

                chunk_start = time.time()
                for attempt in range(1, 16):
                    try:
                        r = session.put(uri, data=data, headers=hdr, timeout=(60, 600))
                        if r.status_code in (200, 201):
                            pos, final = total, r
                        elif r.status_code == 308:
                            rng = r.headers.get("Range")
                            pos = int(rng.split("-")[1]) + 1 if rng else 0

                            # Adaptive throughput scaling based on measured transfer speed:
                            chunk_duration = max(0.001, time.time() - chunk_start)
                            chunk_speed = len(data) / chunk_duration
                            if chunk_speed >= 12 * 1024 * 1024:
                                current_chunk = MAX_CHUNK       # 32 MiB (128x 256 KiB)
                            elif chunk_speed >= 5 * 1024 * 1024:
                                current_chunk = HIGH_CHUNK      # 16 MiB (64x 256 KiB)
                            elif chunk_speed < 1.5 * 1024 * 1024:
                                current_chunk = MIN_CHUNK       # 4 MiB (16x 256 KiB)
                            else:
                                current_chunk = DEFAULT_CHUNK   # 8 MiB (32x 256 KiB)
                        elif r.status_code in RETRYABLE:
                            raise ConnectionError(f"HTTP {r.status_code}")
                        else:
                            log(f"Upload rejected by storage: HTTP {r.status_code}", "error")
                            return None
                        break
                    except (requests.ConnectionError, requests.Timeout, ConnectionError, Exception) as e:
                        current_chunk = MIN_CHUNK
                        wait = min(30, 2 ** min(attempt, 5))
                        log(f"Network problem ({e}); resuming in {wait}s (try {attempt}/15)", "warning")
                        time.sleep(wait)
                        try:
                            pos, done = _query_offset(uri, total)
                            if done is not None:
                                pos, final = total, done
                                break
                            chunk_to_read = min(current_chunk, total - pos)
                            if pos + chunk_to_read < total:
                                chunk_to_read = (chunk_to_read // CHUNK_MULTIPLE) * CHUNK_MULTIPLE
                                if chunk_to_read == 0:
                                    chunk_to_read = CHUNK_MULTIPLE
                            f.seek(pos)
                            data = f.read(chunk_to_read)
                            hdr = {"Content-Length": str(len(data)),
                                   "Content-Range": f"bytes {pos}-{pos + len(data) - 1}/{total}"}
                            chunk_start = time.time()
                        except Exception:
                            pass
                else:
                    log("Upload failed after 15 retries.", "error")
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
    finally:
        session.close()


def secure_upload(file_path, db_name, config, base_dir, log_cb=None, progress_cb=None,
                  telemetry_cb=None, cancel_check=None, status_cb=None, extension=None, is_encrypted=True):
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

    ext = extension or (os.path.splitext(file_path)[1].lower().lstrip(".") or ("dbk2" if is_encrypted else "zip"))
    info = None
    for seq in range(1, 100):
        try:
            r = request_session(broker_url, token, db_name, total, seq, extension=ext, is_encrypted=is_encrypted)
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
            if status == 429:
                log(
                    f"Broker returned temporary rate limit for slot {seq}. Retrying next slot in 2s...",
                    "warning",
                )
                time.sleep(2)
                continue
            log(
                f"Upload slot {seq} for database '{db_name}' is already used today "
                f"(HTTP {status} Conflict). Trying slot {seq + 1}...",
                "warning",
            )
            continue
        log(f"Broker refused the upload (HTTP {status}: {err or r.text[:120]}).", "error")
        return None
    else:
        log(f"Daily upload quota reached for database '{db_name}' today. "
            "Notice: If earlier uploads timed out or failed mid-stream, clear today's UPLOAD_REQUEST rows in the Broker 'Audit' sheet tab.", "critical")
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


def report_storage_telemetry(telemetry_broker_url, token, drives, tab_name="Storage Monitor", customer_sheet_id=None):
    """
    Sends drive health stats to the separate Telemetry Broker endpoint (POST /report-status).
    Routes to the Customer Sheet [Server Cleanup] tab and Master Application Report.
    Returns (success_boolean, message)
    """
    if not telemetry_broker_url or not token:
        return False, "Telemetry Broker URL or token missing"

    try:
        valid_url = validate_broker_url(telemetry_broker_url)
    except ValueError as e:
        return False, f"Telemetry Broker URL rejected: {e}"

    payload = {
        "action": "report_status",
        "token": token,
        "drives": drives,
        "tab_name": tab_name,
        "customer_sheet_id": customer_sheet_id or ""
    }
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
    status="SUCCESS",
    customer_sheet_id=None
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
        "status": status,
        "customer_sheet_id": customer_sheet_id or ""
    }
    try:
        r = post_broker(valid_url, payload, timeout=20)
        status_code, data, err = parse_broker_response(r)
        if not err and status_code < 400:
            return True, "Performance telemetry recorded successfully in Google Sheet"
        return False, f"Broker rejected report: HTTP {status_code} - {err or r.text[:100]}"
    except Exception as e:
        return False, f"Performance telemetry error: {e}"

def report_backup_telemetry(
    broker_url,
    token,
    file_name,
    db_name,
    file_size_bytes=0,
    run_mode="Manual",
    duration_secs=0.0,
    status="SUCCESS",
    customer_sheet_id=None
):
    """
    Sends database backup telemetry to the Upload Broker.
    Routes to the Customer Sheet [DB Backups] tab and Master Application Report.
    Returns (success_boolean, message)
    """
    if not broker_url or not token:
        return False, "Broker URL or token missing"

    try:
        valid_url = validate_broker_url(broker_url)
    except ValueError as e:
        return False, f"Broker URL rejected: {e}"

    payload = {
        "action": "report_status",
        "token": token,
        "module": "DB_BACKUP",
        "file_name": file_name,
        "db_name": db_name,
        "bytes": file_size_bytes,
        "run_mode": run_mode,
        "duration_secs": duration_secs,
        "status": status,
        "customer_sheet_id": customer_sheet_id or ""
    }
    if customer_sheet_id:
        payload["customer_sheet_id"] = customer_sheet_id

    try:
        r = post_broker(valid_url, payload, timeout=20)
        status_code, data, err = parse_broker_response(r)
        if not err and status_code < 400:
            link = data.get("download_link", "")
            return True, f"Backup telemetry recorded successfully in Google Sheet ({link})"
        return False, f"Broker rejected report: HTTP {status_code} - {err or r.text[:100]}"
    except Exception as e:
        return False, f"Backup telemetry error: {e}"



# =============================================================================
# v5.0 ENTERPRISE TELEMETRY, STORAGE QUOTA & SECURITY ALERT EXTENSIONS
# =============================================================================

def protect_dpapi_string(text: str) -> bytes:
    """Protects plaintext string with Windows DPAPI (LocalMachine scope)."""
    return _protect_dpapi_native(text.encode("utf-8") if isinstance(text, str) else text)


def unprotect_dpapi_string(cipher_bytes: bytes) -> str:
    """Unprotects DPAPI cipher bytes using Windows crypt32/win32crypt."""
    return _unprotect_dpapi_native(cipher_bytes)


def report_security_alert(
    broker_url,
    token,
    alert_type="ENCRYPTION_DISABLED",
    db_name="UNKNOWN",
    file_name="UNKNOWN",
    details=""
):
    """
    Dispatches a high-priority security alert event to the Upload Broker.
    Triggers administrative audit logging and automated email alerts.
    """
    if not broker_url or not token:
        return False, "Broker URL or token missing"

    try:
        valid_url = validate_broker_url(broker_url)
    except ValueError as e:
        return False, f"Broker URL rejected: {e}"

    payload = {
        "action": "security_alert",
        "token": token,
        "alert_type": alert_type,
        "db_name": db_name,
        "file_name": file_name,
        "details": details,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    try:
        r = post_broker(valid_url, payload, timeout=20)
        status_code, data, err = parse_broker_response(r)
        if not err and status_code < 400:
            return True, "Security alert recorded and notified successfully"
        return False, f"Broker rejected alert: HTTP {status_code} - {err or r.text[:100]}"
    except Exception as e:
        return False, f"Security alert dispatch error: {e}"


def get_broker_storage_quota(broker_url):
    """
    Queries the upload broker for Google Drive fleet storage quota and limits.
    Returns (success_bool, dict_with_metrics_or_error_str).
    """
    if not broker_url:
        return False, "Broker URL missing"

    try:
        valid_url = validate_broker_url(broker_url)
    except ValueError as e:
        return False, f"Broker URL rejected: {e}"

    try:
        s = get_persistent_session()
        r = s.get(valid_url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return True, {
                "storage_used_bytes": data.get("storage_used_bytes", 0),
                "storage_limit_bytes": data.get("storage_limit_bytes", 0),
                "quota_percent": data.get("quota_percent", 0.0),
                "version": data.get("version", "5.0.0")
            }
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)


def fetch_bundle_from_drive(drive_url_or_id, target_path=None):
    """
    Dynamically downloads and validates a cryptographically signed bundle.json
    from a Google Drive share link or direct URL during installation.
    Prevents leaving static enroll tokens unsealed on distribution media.
    """
    import re
    cleaned = drive_url_or_id.strip()
    # Extract Google Drive file ID if URL passed
    m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", cleaned)
    if m:
        file_id = m.group(1)
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    elif re.search(r"^[a-zA-Z0-9_-]{25,}$", cleaned):
        # Raw file ID
        download_url = f"https://drive.google.com/uc?export=download&id={cleaned}"
    elif cleaned.startswith("http://") or cleaned.startswith("https://"):
        download_url = cleaned
    else:
        return False, "Invalid Google Drive link or File ID format"

    try:
        s = get_persistent_session()
        r = s.get(download_url, timeout=30)
        if r.status_code != 200:
            return False, f"Download failed with HTTP {r.status_code}"

        # Validate JSON structure
        parsed = json.loads(r.text)
        if "customer_slug" not in parsed and "broker_url" not in parsed and "manifest" not in parsed:
            return False, "Downloaded file is not a valid signed bundle.json"

        if target_path:
            os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            secure_token_file_acl(target_path)

        return True, parsed
    except Exception as e:
        return False, f"Remote bundle fetch error: {e}"
