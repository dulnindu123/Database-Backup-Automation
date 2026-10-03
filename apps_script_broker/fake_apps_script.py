import json
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)

# Fake states
fake_db = {
    "tokens": {"test-pc-01": "testhash123"},
    "audit": []
}

@app.route("/", methods=["POST"])
def do_post():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload", "code": 400})

    action = data.get("action")
    
    if action == "enroll":
        if data.get("enroll_code") == "SECRET123":
            return jsonify({"status": "enrolled", "offset_minutes": 10})
        return jsonify({"error": "Unauthorized", "code": 401})

    token = data.get("token")
    if not token or token != "test-pc-01.testhash123":
        return jsonify({"error": "Unauthorized", "code": 401})

    if action == "verify":
        return jsonify({"pc_id": "test-pc-01", "offset_minutes": 10})
    
    elif action == "request_upload":
        db_name = data.get("db_name", "")
        # Mocking resumable upload URI to localhost
        return jsonify({
            "upload_url": "http://localhost:5001/fake_drive_upload_uri",
            "file_name": f"test-pc-01_{db_name}_2026-10-03_1.dbk2"
        })
        
    elif action == "report_status":
        return jsonify({"status": "recorded"})
        
    return jsonify({"error": "Unknown action", "code": 400})

@app.route("/fake_drive_upload_uri", methods=["PUT", "POST"])
def fake_drive():
    # Fake resumable upload endpoint
    return "", 200

if __name__ == "__main__":
    app.run(port=5000)
