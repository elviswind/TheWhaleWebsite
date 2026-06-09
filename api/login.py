from http.server import BaseHTTPRequestHandler
import json
import os
import hmac
import hashlib
import time

SESSION_TTL = 60 * 60 * 24  # 24 hours


def _sign(exp: str) -> str:
    """HMAC the expiry using the configured password as the key, so changing
    the password invalidates every outstanding session — no extra secret."""
    key = os.environ.get("APP_PASSWORD", "").encode()
    return hmac.new(key, exp.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    return f"{exp}.{_sign(exp)}"


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        username = os.environ.get("APP_USERNAME")
        password = os.environ.get("APP_PASSWORD")
        if not username or not password:
            return self._json(503, {"error": "Auth is not configured on the server"})

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Invalid JSON body"})

        # Compute both comparisons before branching to avoid leaking which
        # field was wrong via timing.
        user_ok = hmac.compare_digest(str(body.get("username", "")), username)
        pass_ok = hmac.compare_digest(str(body.get("password", "")), password)
        if not (user_ok and pass_ok):
            return self._json(401, {"error": "Invalid username or password"})

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
