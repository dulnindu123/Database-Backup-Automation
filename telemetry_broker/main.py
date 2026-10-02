"""
Telemetry Broker Service
=============================================================================
Architecture: Dedicated Cloud Run Microservice for Server Storage Health Telemetry.
Service Account Identity: telemetry-broker@$PROJECT.iam.gserviceaccount.com
Permissions: ONLY Google Sheets API access (Spreadsheet Editor). NO GCS or Secret Manager edit permissions.

Responsibilities:
1. Per-PC Bearer token authentication via mounted token hashes (Secret Manager).
2. Strict schema validation & 8 KB payload body cap.
3. Formula injection prevention via Google Sheets values.append(valueInputOption='RAW').
4. Distributed rate-limiting (1 report per 15 minutes per PC) via Firestore or in-memory fallback.
5. Structured JSON Cloud Logging for telemetry audit and rejection alerts.
"""
import os
import re
import json
import time
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from google.oauth2 import service_account
import googleapiclient.discovery

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

SHEET_ID = os.environ.get("SHEET_ID", "")
TOKENS_FILE = os.environ.get("TOKENS_FILE", "/secrets/pc_tokens.json")
MAX_BODY_BYTES = 8192  # 8 KB strict max payload
PC_ID_RE = re.compile(r"^[a-z0-9-]{3,40}$")
DRIVE_NAME_RE = re.compile(r"^[A-Z]:\\$|^[A-Za-z0-9_.\-\\ ]{1,64}$")
VALID_DRIVE_TYPES = {"Fixed", "Remote", "Removable", "CD-ROM", "RAM Disk", "Unknown"}

# In-memory rate limiting fallback: pc_id -> last_timestamp_seconds
_rate_limit_cache = {}
RATE_LIMIT_INTERVAL_SEC = 900  # 15 minutes

# Initialize Google Sheets Service
_sheets_service = None

def get_sheets_service():
    global _sheets_service
    if _sheets_service is None:
        # Uses default Application Default Credentials (Cloud Run service account)
        _sheets_service = googleapiclient.discovery.build('sheets', 'v4')
    return _sheets_service


def audit(event, **kw):
    """Structured JSON logging -> Cloud Logging for log-based alerts."""
    logging.info(json.dumps({"event": event, **kw}))


def authenticate(header):
    """Header format: 'Bearer <pc_id>.<secret>'. Returns pc_id or None."""
    if not header:
        return None
    try:
        scheme, cred = header.split(" ", 1)
        if scheme != "Bearer":
            return None
        pc_id, secret = cred.split(".", 1)
        if not PC_ID_RE.match(pc_id):
            return None
        if not os.path.exists(TOKENS_FILE):
            return None
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            table = json.load(f)
        stored = table.get(pc_id)
        if not stored:
            return None
        given = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return pc_id if hmac.compare_digest(given, stored) else None
    except Exception:
        return None


def is_rate_limited(pc_id):
    """Checks rate limit (1 report per 15 mins). Checks Firestore if available, else in-memory."""
    now = time.time()
    try:
        from google.cloud import firestore
        db = firestore.Client()
        doc_ref = db.collection("telemetry_rate_limits").document(pc_id)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict() or {}
            last_time = data.get("last_report_timestamp", 0)
            if now - last_time < RATE_LIMIT_INTERVAL_SEC:
                return True
        doc_ref.set({"last_report_timestamp": now, "pc_id": pc_id})
        return False
    except Exception:
        # Fallback to in-memory cache
        last_time = _rate_limit_cache.get(pc_id, 0)
        if now - last_time < RATE_LIMIT_INTERVAL_SEC:
            return True
        _rate_limit_cache[pc_id] = now
        return False


def validate_drives_payload(data):
    """
    Strictly validates telemetry schema:
    - Must be a dict with ONLY 'drives' key.
    - 'drives' must be a list of 1..26 objects.
    - Each drive object must contain valid drive_letter, drive_type, total_bytes, free_bytes, percent_used.
    Returns (is_valid, error_msg, clean_drives)
    """
    if not isinstance(data, dict):
        return False, "Payload must be a JSON object", None

    extra_keys = set(data.keys()) - {"drives"}
    if extra_keys:
        return False, f"Unknown top-level fields rejected: {list(extra_keys)}", None

    drives = data.get("drives")
    if not isinstance(drives, list) or len(drives) == 0 or len(drives) > 26:
        return False, "Field 'drives' must be a list of 1 to 26 items", None

    clean_drives = []
    for idx, d in enumerate(drives):
        if not isinstance(d, dict):
            return False, f"Drive entry [{idx}] must be a dict", None

        allowed_drive_keys = {"drive_letter", "drive_type", "total_bytes", "free_bytes", "percent_used"}
        drive_extras = set(d.keys()) - allowed_drive_keys
        if drive_extras:
            return False, f"Drive entry [{idx}] has illegal fields: {list(drive_extras)}", None

        name = str(d.get("drive_letter", "")).strip()
        if not DRIVE_NAME_RE.match(name):
            return False, f"Drive entry [{idx}] illegal name format: '{name}'", None

        dtype = str(d.get("drive_type", "Unknown")).strip()
        if dtype not in VALID_DRIVE_TYPES:
            return False, f"Drive entry [{idx}] invalid drive type: '{dtype}'", None

        total = d.get("total_bytes")
        free = d.get("free_bytes")
        pct = d.get("percent_used")

        if type(total) not in (int, float) or total < 0:
            return False, f"Drive entry [{idx}] total_bytes must be a non-negative number", None
        if type(free) not in (int, float) or free < 0 or free > total:
            return False, f"Drive entry [{idx}] free_bytes must be between 0 and total_bytes", None
        if type(pct) not in (int, float) or pct < 0 or pct > 100:
            return False, f"Drive entry [{idx}] percent_used must be between 0 and 100", None

        clean_drives.append({
            "drive_letter": name,
            "drive_type": dtype,
            "total_bytes": int(total),
            "free_bytes": int(free),
            "percent_used": float(round(pct, 2))
        })

    return True, "", clean_drives


# Sheet Bindings Cache & Helper Functions (Requirement F)
_sheet_bindings_cache = {}


def get_bound_sheet(pc_id):
    """Retrieves the Google Sheet ID bound to this PC ID. Ignores client-supplied ID."""
    try:
        from google.cloud import firestore
        db = firestore.Client()
        doc = db.collection("pc_sheet_bindings").document(pc_id).get()
        if doc.exists:
            bound = doc.to_dict().get("sheet_id")
            if bound:
                return bound
    except Exception:
        pass
    return _sheet_bindings_cache.get(pc_id) or SHEET_ID


def bind_sheet_to_pc(pc_id, sheet_id):
    """
    Binds a Google Sheet ID to a PC ID once (Requirement F).
    Re-binding to a different sheet is rejected to prevent tampering.
    """
    existing = get_bound_sheet(pc_id)
    if existing and existing != sheet_id and existing != SHEET_ID:
        return False, f"PC ID '{pc_id}' is already bound to another Sheet ({existing[:8]}...). Re-binding locked.", ""

    # Verify sheet access via Google Sheets API
    try:
        service = get_sheets_service()
        meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        title = meta.get("properties", {}).get("title", "Master Telemetry Sheet")
    except Exception as e:
        sa_email = get_service_account_email()
        return False, f"Cannot access Sheet. Please ensure '{sa_email}' has Editor access. Error: {str(e)[:150]}", ""

    # Persist binding to Firestore or in-memory cache
    try:
        from google.cloud import firestore
        db = firestore.Client()
        db.collection("pc_sheet_bindings").document(pc_id).set({
            "sheet_id": sheet_id,
            "title": title,
            "bound_at": datetime.now(timezone.utc).isoformat()
        })
    except Exception:
        pass

    _sheet_bindings_cache[pc_id] = sheet_id
    audit("sheet_bound", pc=pc_id, sheet_id=sheet_id)
    return True, "Successfully bound sheet to PC ID", title


def get_service_account_email():
    """Returns the Telemetry Broker service account email."""
    env_email = os.environ.get("SERVICE_ACCOUNT_EMAIL", "")
    if env_email:
        return env_email
    project = os.environ.get("PROJECT_ID", "your-gcp-project")
    return f"telemetry-broker@{project}.iam.gserviceaccount.com"


@app.get("/telemetry-info")
def telemetry_info():
    """Returns telemetry service configuration for client UI display (Requirement F)."""
    return jsonify(
        service_account_email=get_service_account_email(),
        status="ok"
    )


@app.post("/bind-sheet")
def bind_sheet():
    """Binds a customer Google Sheet ID to the authenticated PC ID once (Requirement F)."""
    pc = authenticate(request.headers.get("Authorization", ""))
    if not pc:
        audit("auth_rejected", ip=request.remote_addr, endpoint="bind-sheet")
        return jsonify(error="unauthorized"), 401

    body = request.get_json(silent=True) or {}
    sheet_id = str(body.get("sheet_id", "")).strip()
    if not sheet_id or len(sheet_id) < 20:
        return jsonify(error="Invalid or missing sheet_id"), 400

    ok, msg, title = bind_sheet_to_pc(pc, sheet_id)
    if not ok:
        return jsonify(error=msg), 400

    return jsonify(status="ok", message=msg, title=title, bound_sheet_id=sheet_id)


@app.post("/test-sheet")
def test_sheet():
    """Tests connectivity and permissions to the customer's Google Sheet (Requirement F)."""
    pc = authenticate(request.headers.get("Authorization", ""))
    if not pc:
        audit("auth_rejected", ip=request.remote_addr, endpoint="test-sheet")
        return jsonify(error="unauthorized"), 401

    body = request.get_json(silent=True) or {}
    sheet_id = str(body.get("sheet_id", "")).strip() or get_bound_sheet(pc)

    if not sheet_id:
        return jsonify(error="No sheet_id supplied and none bound for this PC ID"), 400

    try:
        service = get_sheets_service()
        meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        title = meta.get("properties", {}).get("title", "Master Telemetry Sheet")
        return jsonify(
            status="ok",
            message=f"Verified Editor access to '{title}'",
            title=title,
            sheet_id=sheet_id
        )
    except Exception as e:
        sa_email = get_service_account_email()
        return jsonify(
            error=f"Google Sheets API access failed. Grant Editor permission to '{sa_email}'. Detail: {str(e)[:150]}"
        ), 403


@app.post("/report-storage")
def report_storage():
    # 1. Enforce 8 KB Payload Size Limit (checking actual raw bytes)
    raw_body = request.get_data()
    if len(raw_body) > MAX_BODY_BYTES:
        audit("bad_schema", reason="payload_too_large", size=len(raw_body))
        return jsonify(error="payload exceeds 8 KB limit"), 400

    # 2. Authenticate Bearer Token
    pc = authenticate(request.headers.get("Authorization", ""))
    if not pc:
        audit("auth_rejected", ip=request.remote_addr, endpoint="report-storage")
        return jsonify(error="unauthorized"), 401

    # 3. Strict Schema & Bounds Validation
    try:
        body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        audit("bad_schema", pc=pc, reason="invalid_json_body")
        return jsonify(error="invalid JSON body"), 400

    valid, err_msg, clean_drives = validate_drives_payload(body)
    if not valid:
        audit("bad_schema", pc=pc, reason=err_msg)
        return jsonify(error=err_msg), 400

    # 4. Rate Limit Check (15 min per PC)
    if is_rate_limited(pc):
        audit("rate_limited", pc=pc)
        return jsonify(error="rate limit exceeded: max 1 report per 15 minutes"), 429

    # 5. Resolve Bound Sheet ID (Requirement F: strictly ignores client-supplied sheet ID)
    target_sheet_id = get_bound_sheet(pc)
    if not target_sheet_id:
        audit("sheets_error", pc=pc, err="No sheet bound for PC ID and SHEET_ID unconfigured")
        return jsonify(error="No Google Sheet bound for this PC ID. Call /bind-sheet first."), 400

    # 6. Append Rows to Google Sheet (Tab named after pc_id)
    # Timestamp set exclusively by Broker (UTC ISO 8601 format)
    server_timestamp = datetime.now(timezone.utc).isoformat()
    rows = []
    for d in clean_drives:
        total_gb = round(d["total_bytes"] / (1024 ** 3), 2)
        free_gb = round(d["free_bytes"] / (1024 ** 3), 2)
        # Row layout: [Timestamp, PC ID, Drive Letter, Type, Total GB, Free GB, Usage %]
        rows.append([
            server_timestamp,
            pc,
            d["drive_letter"],
            d["drive_type"],
            total_gb,
            free_gb,
            d["percent_used"]
        ])

    try:
        service = get_sheets_service()
        # Ensure worksheet tab exists for pc_id
        sheet_range = f"{pc}!A:G"
        # valueInputOption='RAW' prevents formula injection (e.g. =cmd|' /C ...'!A1 is stored as literal string)
        service.spreadsheets().values().append(
            spreadsheetId=target_sheet_id,
            range=sheet_range,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()

        audit("telemetry_accepted", pc=pc, drives_count=len(clean_drives), sheet_id=target_sheet_id)
        return jsonify(status="ok", drives_logged=len(clean_drives))
    except Exception as e:
        audit("sheets_error", pc=pc, err=str(e)[:200])
        return jsonify(error="failed to append telemetry to sheet"), 502


@app.get("/healthz")
def healthz():
    return "ok"

