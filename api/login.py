import os
import sys
import json
import hmac
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _common import make_token, respond, SESSION_TTL  # noqa: E402

# --- Brute-force throttling -------------------------------------------------
# Best-effort, in-memory, per-IP lockout. NOTE: serverless instances are
# ephemeral and there can be several warm at once, so this is not a hard
# guarantee — it slows down a single attacker hammering one instance. For
# strong protection use a shared store (Vercel KV / Upstash Redis).
MAX_FAILS = 5          # failures allowed within the window
WINDOW = 15 * 60       # rolling window / lockout length, seconds
FAIL_DELAY = 1.0       # artificial delay on each failed attempt, seconds

_failures = defaultdict(list)  # ip -> [timestamps of recent failures]


def _client_ip(headers) -> str:
    xff = headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() or "unknown"


def _recent_failures(ip: str):
    now = time.time()
    recent = [t for t in _failures[ip] if now - t < WINDOW]
    _failures[ip] = recent
    return recent


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Tolerate stray whitespace/newlines pasted into the env vars.
        username = (os.environ.get("APP_USERNAME") or "").strip()
        password = (os.environ.get("APP_PASSWORD") or "").strip()
        if not username or not password:
            return respond(self, 503, {"error": "Auth is not configured on the server"})

        ip = _client_ip(self.headers)
        if len(_recent_failures(ip)) >= MAX_FAILS:
            return respond(
                self, 429,
                {"error": "Too many failed attempts. Try again later."},
                extra_headers=[("Retry-After", str(WINDOW))],
            )

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return respond(self, 400, {"error": "Invalid JSON body"})

        # Compute both comparisons before branching to avoid leaking which
        # field was wrong via timing.
        user_ok = hmac.compare_digest(str(body.get("username", "")).strip(), username)
        pass_ok = hmac.compare_digest(str(body.get("password", "")).strip(), password)
        if not (user_ok and pass_ok):
            _failures[ip].append(time.time())
            time.sleep(FAIL_DELAY)
            return respond(self, 401, {"error": "Invalid username or password"})

        _failures.pop(ip, None)  # reset on success
        cookie = (
            f"auth={make_token()}; HttpOnly; Secure; SameSite=Lax; "
            f"Path=/; Max-Age={SESSION_TTL}"
        )
        respond(self, 200, {"ok": True}, extra_headers=[("Set-Cookie", cookie)])

    def do_DELETE(self):
        # Logout: expire the cookie immediately.
        cookie = "auth=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"
        respond(self, 200, {"ok": True}, extra_headers=[("Set-Cookie", cookie)])
