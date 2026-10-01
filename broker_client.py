"""
App-side client for the upload broker. The app holds NO Google credentials.
Its only secret is a per-PC broker token that can request "start an upload" and nothing else.
"""
import os, time, base64, hashlib, requests

CHUNK = 8 * 1024 * 1024  # must be a multiple of 256 KiB for GCS resumable uploads
RETRYABLE = (429, 500, 502, 503, 504)


# ---- token storage (Windows DPAPI, machine scope; native crypt32.dll + fallback) ----
CRYPTPROTECT_LOCAL_MACHINE = 0x4
CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _protect_dpapi_native(data_bytes):
    """Protects data with Windows DPAPI (LocalMachine scope) using system crypt32.dll."""
    if os.name != "nt":
        return data_bytes
    try:
        import ctypes
        from ctypes import wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(data_bytes), ctypes.cast(ctypes.c_char_p(data_bytes), ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        flags = CRYPTPROTECT_LOCAL_MACHINE | CRYPTPROTECT_UI_FORBIDDEN
        if not crypt32.CryptProtectData(ctypes.byref(blob_in), "BackupBrokerToken", None, None, None, flags, ctypes.byref(blob_out)):
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
    """Unprotects DPAPI data using system crypt32.dll with win32crypt and plain fallback."""
    if os.name != "nt":
        return cipher_bytes.decode(errors="ignore").strip()
    try:
        import ctypes
        from ctypes import wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        blob_in = DATA_BLOB(len(cipher_bytes), ctypes.cast(ctypes.c_char_p(cipher_bytes), ctypes.POINTER(ctypes.c_char)))
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
            return cipher_bytes.decode("utf-8", errors="ignore").strip()


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
        if os.environ.get("ALLOW_INSECURE_BROKER", "").lower() == "true":
            return clean
        raise ValueError(
            "Insecure HTTP broker URL rejected in production. "
            "Local HTTP is allowed only if ALLOW_INSECURE_BROKER=true is set."
        )
    raise ValueError(
        f"Insecure or invalid broker URL '{clean}'. Only HTTPS is permitted in production."
    )


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
                try:
                    os.remove(raw_token_input)
                except Exception:
                    pass
    return True


# ---- broker + storage ----
def _md5_b64(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(blk)
    return base64.b64encode(h.digest()).decode()


def request_session(broker_url, token, db, size, seq=1):
    valid_url = validate_broker_url(broker_url)
    r = requests.post(valid_url.rstrip("/") + "/request-upload",
                      json={"db": db, "size": size, "seq": seq},
                      headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return r


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

    for seq in (1, 2, 3):  # 409 = slot used today (e.g. an earlier run); try the next slot
        try:
            r = request_session(broker_url, token, db_name, total, seq)
        except requests.RequestException as e:
            log(f"Broker unreachable: {e}", "error")
            return None
        except ValueError as e:
            log(f"Broker configuration error: {e}", "critical")
            return None
        if r.status_code == 200:
            info = r.json()
            break
        if r.status_code == 409:
            log(f"Upload slot {seq}/3 for database '{db_name}' is already used today (HTTP 409 Conflict). Trying slot {seq+1}...", "warning")
            continue
        log(f"Broker refused the upload (HTTP {r.status_code}: {r.text[:120]}).", "error")
        return None
    else:
        log(f"SECURITY ALERT: All 3 upload slots for database '{db_name}' are exhausted today. "
            f"If you did not execute 3 backups today, your token may be compromised or experiencing slot-burning.", "critical")
        return None

    if status_cb:
        status_cb(f"Uploading {os.path.basename(file_path)} ...")
    resp = _put_all(info["session_uri"], file_path, total, log, progress_cb, telemetry_cb, cancel_check)
    if resp is None:
        return None

    remote_md5 = resp.json().get("md5Hash")
    if remote_md5 != _md5_b64(file_path):
        log("Integrity check FAILED: remote checksum differs from local file.", "critical")
        return None
    log(f"Upload verified (MD5 match): {info['object']}", "info")
    return info["object"]


def report_storage_telemetry(telemetry_broker_url, token, drives):
    """
    Sends drive health stats to the separate Telemetry Broker endpoint (POST /report-storage).
    Note: Client NEVER sends a Sheet ID or tab name. The broker handles sheet insertion safely.
    Returns (success_boolean, message)
    """
    if not telemetry_broker_url or not token:
        return False, "Telemetry Broker URL or token missing"

    try:
        valid_url = validate_broker_url(telemetry_broker_url)
    except ValueError as e:
        return False, f"Telemetry Broker URL rejected: {e}"

    payload = {"drives": drives}
    try:
        r = requests.post(
            valid_url.rstrip("/") + "/report-storage",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15
        )
        if r.status_code == 200:
            return True, f"Telemetry reported ({r.json().get('drives_logged', len(drives))} drives logged)"
        elif r.status_code == 429:
            return False, "Telemetry rate limited (max 1 report per 15 mins)"
        else:
            return False, f"Telemetry broker rejected report: HTTP {r.status_code} - {r.text[:100]}"
    except Exception as e:
        return False, f"Telemetry broker error: {e}"
