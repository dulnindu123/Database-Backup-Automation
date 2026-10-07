"""
Lightweight development & test broker server.
Uses Python standard library http.server (no Flask/external dependencies required).
"""
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class DevBrokerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "dev_broker", "message": "HTTP 200"}).encode())

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_len) if content_len else b"{}"
        try:
            data = json.loads(post_body.decode('utf-8'))
        except Exception:
            data = {}

        path = self.path
        action = data.get("action", "")
        token = data.get("token", "")

        if path in ("/health", "/healthz") or action == "health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "HTTP 200"}).encode())
            return

        if path in ("/verify",) or action == "verify":
            if token and "." in token and not token.startswith("invalid"):
                pc_id = token.split(".")[0]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "pc_id": pc_id, "offset_minutes": 10}).encode())
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized", "code": 401}).encode())
            return

        if path in ("/request-upload",) or action == "request_upload":
            host = self.headers.get('Host', '127.0.0.1')
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "upload_url": f"http://{host}/upload/test-session-123",
                "file_name": "backup.dbk2"
            }).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def do_PUT(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "uploaded"}).encode())

    def log_message(self, format, *args):
        pass  # Suppress console logging during unit tests


class DevBrokerServer:
    def __init__(self, host="127.0.0.1", port=8088):
        self.host = host
        self.port = port
        self.server = HTTPServer((host, port), DevBrokerHandler)
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)


def run_dev_server(host="127.0.0.1", port=8088):
    server = HTTPServer((host, port), DevBrokerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
