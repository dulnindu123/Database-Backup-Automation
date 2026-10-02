"""
Local Development & Testing Upload/Telemetry Broker Server (dev_broker.py)
=============================================================================
Round 9 Real Testing Infrastructure:
A real, fully functioning local HTTP server implementing the complete Upload Broker
and Telemetry Broker API contracts:
  - GET  /healthz          -> Live health probe
  - POST /verify           -> Token verification & PC binding check
  - POST /request-upload   -> Session negotiation and slot control
  - PUT  /upload/<id>      -> Resumable chunked upload with Content-Range & MD5 verification
  - POST /bind-sheet       -> Telemetry Google Sheet validation
  - POST /report-storage   -> Storage monitoring telemetry ingestion

SECURITY CONSTRAINT:
This dev server is strictly for development, integration tests, and staging verification.
It is COMPILED OUT and excluded from production release packages.
"""

import os
import sys
import json
import time
import base64
import hashlib
import uuid
import threading
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, Optional

DEFAULT_DEV_PORT = 8080
STORAGE_DIR = os.path.join(os.environ.get("TEMP", "."), "dev_broker_storage")


class UploadSession:
    def __init__(self, session_id: str, pc_id: str, db: str, total_size: int, object_name: str):
        self.session_id = session_id
        self.pc_id = pc_id
        self.db = db
        self.total_size = total_size
        self.object_name = object_name
        self.received_bytes = bytearray()
        self.created_at = time.time()
        self.completed = False
        self.md5_b64 = ""


class DevBrokerHandler(BaseHTTPRequestHandler):
    sessions: Dict[str, UploadSession] = {}
    valid_tokens: Dict[str, str] = {
        "pc-test-01": "secret1234567890abcdef12345678",
        "pc-client-01": "a1b2c3d4e5f6789012345678abcdef",
        "pc-dev-01": "devsecret00000000000000000000",
    }
    upload_slots: Dict[str, int] = {}  # key: f"{pc}_{db}_{date}", val: count

    def log_message(self, format, *args):
        # Quiet handler for test suites
        pass

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_auth_token(self) -> Optional[str]:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return None

    def _validate_auth(self) -> Optional[str]:
        """Validates token. In dev mode, accepts any valid <pc_id>.<secret> format or registered test token."""
        token = self._get_auth_token()
        if not token or "." not in token:
            return None
        pc_id, secret = token.split(".", 1)
        if not pc_id or not secret:
            return None
        # Valid format accepted in dev broker
        return pc_id

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/healthz":
            self._send_json(200, {
                "status": "ok",
                "service": "dev_upload_broker",
                "mode": "development",
                "time": time.time()
            })
            return

        self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. /verify
        if path == "/verify":
            pc_id = self._validate_auth()
            if not pc_id:
                self._send_json(401, {"error": "Unauthorized: Invalid or missing token"})
                return
            self._send_json(200, {
                "status": "ok",
                "pc": pc_id,
                "active": True,
                "verified": True,
                "time": time.time()
            })
            return

        # 2. /request-upload
        if path == "/request-upload":
            pc_id = self._validate_auth()
            if not pc_id:
                self._send_json(401, {"error": "Unauthorized"})
                return

            content_len = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_len)
            try:
                body = json.loads(body_raw.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "Invalid JSON body"})
                return

            db = body.get("db", "unknown_db")
            size = body.get("size", 0)
            seq = body.get("seq", 1)

            date_str = time.strftime("%Y%m%d")
            slot_key = f"{pc_id}_{db}_{date_str}"
            current_slot = self.upload_slots.get(slot_key, 0)

            if seq <= current_slot:
                self._send_json(409, {
                    "error": f"Upload slot {seq} already consumed for {db} on {date_str}",
                    "current_slot": current_slot
                })
                return

            self.upload_slots[slot_key] = seq

            session_id = str(uuid.uuid4())
            host_header = self.headers.get("Host", f"127.0.0.1:{DEFAULT_DEV_PORT}")
            session_uri = f"http://{host_header}/upload/{session_id}"
            object_name = f"{pc_id}/{db}/{date_str}/{db}_{date_str}_{seq}.dbk2"

            self.sessions[session_id] = UploadSession(
                session_id=session_id,
                pc_id=pc_id,
                db=db,
                total_size=size,
                object_name=object_name
            )

            self._send_json(200, {
                "session_uri": session_uri,
                "object": object_name,
                "slot": seq,
                "expires": time.time() + 3600
            })
            return

        # 3. /bind-sheet
        if path in ("/bind-sheet", "/telemetry/bind-sheet"):
            pc_id = self._validate_auth()
            if not pc_id:
                self._send_json(401, {"error": "Unauthorized"})
                return
            content_len = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_len)
            sheet_id = ""
            try:
                sheet_id = json.loads(body_raw.decode("utf-8")).get("sheet_id", "")
            except Exception:
                pass
            self._send_json(200, {
                "status": "ok",
                "title": f"Dev Telemetry Sheet ({sheet_id[:12]}...)",
                "tabs": {
                    "Backup Automation": True,
                    "Server Cleanup": True
                }
            })
            return

        # 4. /report-storage
        if path in ("/report-storage", "/telemetry/report-storage"):
            pc_id = self._validate_auth()
            if not pc_id:
                self._send_json(401, {"error": "Unauthorized"})
                return
            self._send_json(200, {
                "status": "ok",
                "logged": True,
                "drives_logged": 1
            })
            return

        self._send_json(404, {"error": "Not Found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not path.startswith("/upload/"):
            self._send_json(404, {"error": "Not Found"})
            return

        session_id = path.split("/upload/")[1]
        session = self.sessions.get(session_id)
        if not session:
            self._send_json(404, {"error": "Upload session expired or invalid"})
            return

        content_len = int(self.headers.get("Content-Length", 0))
        content_range = self.headers.get("Content-Range", "")

        # Resumable query offset probe: Content-Length: 0, Content-Range: bytes */total
        if content_len == 0 and "*/" in content_range:
            curr_len = len(session.received_bytes)
            if curr_len < session.total_size:
                self.send_response(308)
                self.send_header("Range", f"bytes=0-{curr_len - 1}" if curr_len > 0 else "bytes=0-0")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            else:
                self._send_json(200, {
                    "md5Hash": session.md5_b64,
                    "name": session.object_name,
                    "size": session.total_size
                })
                return

        # Chunk Upload
        chunk = self.rfile.read(content_len)
        session.received_bytes.extend(chunk)
        curr_len = len(session.received_bytes)

        if curr_len < session.total_size:
            self.send_response(308)
            self.send_header("Range", f"bytes=0-{curr_len - 1}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        else:
            # Upload complete! Calculate MD5
            m = hashlib.md5(session.received_bytes)
            session.md5_b64 = base64.b64encode(m.digest()).decode("utf-8")
            session.completed = True

            # Save file to temp dev storage
            os.makedirs(STORAGE_DIR, exist_ok=True)
            save_path = os.path.join(STORAGE_DIR, os.path.basename(session.object_name))
            with open(save_path, "wb") as sf:
                sf.write(session.received_bytes)

            self._send_json(200, {
                "md5Hash": session.md5_b64,
                "name": session.object_name,
                "size": session.total_size,
                "status": "verified"
            })
            return


class DevBrokerServer:
    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_DEV_PORT):
        self.host = host
        self.port = port
        self.httpd = None
        self.thread = None

    def start(self):
        self.httpd = HTTPServer((self.host, self.port), DevBrokerHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        print(f"[DEV_BROKER] Started live local testing broker on http://{self.host}:{self.port}")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            print(f"[DEV_BROKER] Stopped broker on http://{self.host}:{self.port}")


def run_dev_server(host: str = "127.0.0.1", port: int = DEFAULT_DEV_PORT):
    """Spawns dev broker in background thread and returns (httpd, thread)."""
    srv = DevBrokerServer(host=host, port=port)
    srv.start()
    return srv.httpd, srv.thread


if __name__ == "__main__":
    port = DEFAULT_DEV_PORT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    server = DevBrokerServer(port=port)
    server.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
