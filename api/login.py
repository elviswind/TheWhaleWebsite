from http.server import BaseHTTPRequestHandler
from collections import defaultdict
import json
import os
import hmac
import hashlib
import time

SESSION_TTL = 60 * 60 * 24  # 24 hours

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


def _sign(exp: str) -> str:
    """HMAC the expiry using the configured password as the key, so changing
    the password invalidates every outstanding session — no extra secret."""
    key = (os.environ.get("APP_PASSWORD") or "").strip().encode()
    return hmac.new(key, exp.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    return f"{exp}.{_sign(exp)}"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Tolerate stray whitespace/newlines pasted into the env vars.
        username = (os.environ.get("APP_USERNAME") or "").strip()
        password = (os.environ.get("APP_PASSWORD") or "").strip()
        if not username or not password:
            return self._json(503, {"error": "Auth is not configured on the server"})

        ip = _client_ip(self.headers)
        if len(_recent_failures(ip)) >= MAX_FAILS:
            return self._json(
                429,
                {"error": "Too many failed attempts. Try again later."},
                extra_headers=[("Retry-After", str(WINDOW))],
            )

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Invalid JSON body"})

        # Compute both comparisons before branching to avoid leaking which
        # field was wrong via timing.
        user_ok = hmac.compare_digest(str(body.get("username", "")).strip(), username)
        pass_ok = hmac.compare_digest(str(body.get("password", "")).strip(), password)
        if not (user_ok and pass_ok):
            _failures[ip].append(time.time())
            time.sleep(FAIL_DELAY)
            return self._json(401, {"error": "Invalid username or password"})

        _failures.pop(ip, None)  # reset on success
        cookie = (
            f"auth={make_token()}; HttpOnly; Secure; SameSite=Lax; "
            f"Path=/; Max-Age={SESSION_TTL}"
        )
        self._json(200, {"ok": True}, extra_headers=[("Set-Cookie", cookie)])

    def do_DELETE(self):
        # Logout: expire the cookie immediately.
        cookie = "auth=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"
        self._json(200, {"ok": True}, extra_headers=[("Set-Cookie", cookie)])

    def _json(self, status: int, body: dict, extra_headers=None):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in extra_headers or []:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
