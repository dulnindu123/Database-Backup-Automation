"""
Upload broker. The ONLY component that talks to Google Cloud Storage.
Runs on Cloud Run with a service account that has just roles/storage.objectCreator
on one bucket. It exposes ONE action: start an upload of a correctly named object.
There is no list, read, delete, or "choose your own path" endpoint.
"""
import os, re, json, hmac, hashlib, datetime, logging
from flask import Flask, request, jsonify
from google.cloud import storage
from google.api_core.exceptions import PreconditionFailed

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

BUCKET = os.environ.get("BUCKET", "")
TOKENS_FILE = os.environ.get("TOKENS_FILE", "/secrets/pc_tokens.json")  # Secret Manager volume
CUSTOMER_SLUG = os.environ.get("CUSTOMER_SLUG", "").strip().lower()
raw_dbs = os.environ.get("ALLOWED_DBS", "").strip()
ALLOWED_DBS = {d.strip() for d in raw_dbs.split(",") if d.strip() and d.strip().lower() != "all"}
MAX_BYTES = int(os.environ.get("MAX_BYTES", str(100 * 1024 ** 3)))
PC_ID_RE = re.compile(r"^[a-z0-9-]{3,40}$")
DB_NAME_RE = re.compile(r"^[A-Za-z0-9_$-]{1,128}$")

_client = None

def get_storage_client():
    global _client
    if _client is None:
        _client = storage.Client()
    return _client


def audit(event, **kw):
    # Structured JSON -> Cloud Logging. Build log-based alerts on these.
    logging.info(json.dumps({"event": event, **kw}))


def authenticate(header):
    """Header format: 'Bearer <pc_id>.<secret>'. Returns pc_id or None."""
    try:
        scheme, cred = header.split(" ", 1)
        pc_id, secret = cred.split(".", 1)
        if scheme != "Bearer" or not PC_ID_RE.match(pc_id):
            return None
        # Enforce customer binding: pc_id prefix must match customer slug
        if CUSTOMER_SLUG and not pc_id.startswith(f"{CUSTOMER_SLUG}-"):
            audit("customer_mismatch", pc=pc_id, expected_customer=CUSTOMER_SLUG)
            return None
        if not os.path.exists(TOKENS_FILE):
            return None
        with open(TOKENS_FILE) as f:  # re-read each request so revocation is immediate
            table = json.load(f)
        stored = table.get(pc_id)
        if not stored:  # missing or revoked
            return None
        given = hashlib.sha256(secret.encode()).hexdigest()
        return pc_id if hmac.compare_digest(given, stored) else None
    except Exception:
        return None


@app.post("/request-upload")
def request_upload():
    pc = authenticate(request.headers.get("Authorization", ""))
    if not pc:
        audit("auth_rejected", ip=request.remote_addr)
        return jsonify(error="unauthorized"), 401

    body = request.get_json(silent=True) or {}
    db, size, seq = body.get("db"), body.get("size"), body.get("seq", 1)

    # Strict Database Name Validation (No 'all' wildcard, strictly sanitized SQL identifiers)
    if not isinstance(db, str) or not DB_NAME_RE.match(db):
        audit("bad_db", pc=pc, db=str(db)[:50])
        return jsonify(error="invalid database name"), 400
    if ALLOWED_DBS and db not in ALLOWED_DBS:
        audit("db_not_allowed", pc=pc, db=str(db)[:50])
        return jsonify(error="db not allowed"), 400

    if not isinstance(size, int) or isinstance(size, bool) or not (0 < size <= MAX_BYTES):
        audit("bad_size", pc=pc, size=str(size)[:20]); return jsonify(error="bad size"), 400
    if seq not in (1, 2, 3):
        audit("bad_seq", pc=pc); return jsonify(error="bad seq"), 400

    # The BROKER chooses the object name. Client input cannot influence the path.
    # Prefixed with customer slug to satisfy IAM-conditioned objectCreator
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    if CUSTOMER_SLUG:
        name = f"{CUSTOMER_SLUG}/{pc}/{db}/{day}_{seq}.dbk2"
    else:
        name = f"{pc}/{db}/{day}_{seq}.dbk2"
    blob = get_storage_client().bucket(BUCKET).blob(name)
    try:
        # if_generation_match=0 => fail if object already exists (no overwrite).
        uri = blob.create_resumable_upload_session(
            content_type="application/octet-stream", size=size, if_generation_match=0)
    except PreconditionFailed:
        audit("duplicate", pc=pc, object=name)
        return jsonify(error="already uploaded for this slot"), 409
    except Exception as e:
        audit("gcs_error", pc=pc, err=str(e)[:200])
        return jsonify(error="storage error"), 502

    audit("upload_granted", pc=pc, object=name, size=size)
    return jsonify(session_uri=uri, object=name)


@app.post("/verify")
def verify_token():
    pc = authenticate(request.headers.get("Authorization", ""))
    if not pc:
        audit("auth_rejected", ip=request.remote_addr, endpoint="verify")
        return jsonify(error="unauthorized"), 401
    audit("token_verified", pc=pc)
    return jsonify(pc=pc, status="verified")


@app.get("/healthz")
def healthz():
    return "ok"
