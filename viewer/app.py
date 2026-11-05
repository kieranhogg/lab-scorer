import hmac
import os

import time

from flask import Flask, request, Response

app = Flask(__name__, static_folder="static", static_url_path="")

VIEWER_PASSWORD = os.environ.get("VIEWER_PASSWORD")
# Largest terminal capture kept per instance, in characters
MAX_SCREEN = 8000
MAX_TEXT = 100
# A request this big is not a real report
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

# Instances waiting to be told that the instructor has answered their help request
acked = set()
instances = {}

@app.before_request
def require_login():
    if not VIEWER_PASSWORD or request.endpoint == "report":
        return None
    auth = request.authorization
    if auth and hmac.compare_digest(auth.password or "", VIEWER_PASSWORD):
        return None
    return Response(
        "Login required", 401, {"WWW-Authenticate": 'Basic realm="Lab viewer"'}
    )

def _text(value, limit=MAX_TEXT):
    return None if value is None else str(value)[:limit]


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/report")
def report():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get("instance_id"):
        return {"error": "instance_id is required"}, 400
    instance_id = _text(data["instance_id"])
    row = {
        "name": _text(data.get("name")) or instance_id[:6],
        "module": _text(data.get("module")),
        "unit": _text(data.get("unit")),
        "step": _count(data.get("step")),
        "total_steps": _count(data.get("total_steps")),
        "started": bool(data.get("started")),
        "finished": bool(data.get("finished")),
        "help": bool(data.get("help")),
        "screen": _text(data.get("screen"), MAX_SCREEN),
        "last_seen": time.time(),
    }
    ack = instance_id in acked
    if ack:
        # Delivered once, the instance clears its own flag when it sees this
        acked.discard(instance_id)
        row["help"] = False
    instances[instance_id] = row
    return {"ack_help": ack}


@app.post("/api/ack/<instance_id>")
def ack(instance_id):
    row = instances.get(instance_id)
    if row is None:
        return {"error": "unknown instance"}, 404
    row["help"] = False
    acked.add(instance_id)
    return {"ok": True}


@app.get("/api/instances")
def get_instances():
    return instances
