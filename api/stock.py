from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import os
import hmac
import hashlib
import time
import urllib.request
import tempfile

CACHE_KEY = "prices"


def is_authenticated(cookie_header: str) -> bool:
    """Validate the signed `auth` session cookie set by /api/login."""
    password = (os.environ.get("APP_PASSWORD") or "").strip()
    if not password:
        return False  # fail closed when auth isn't configured

    token = None
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == "auth":
            token = value
    if not token or "." not in token:
        return False

    exp, _, sig = token.rpartition(".")
    if not exp.isdigit() or int(exp) < int(time.time()):
        return False

    expected = hmac.new(password.encode(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# --- Vercel KV (Upstash Redis REST) read access ----------------------------
# Inlined per-function (Vercel's Python runtime is unreliable about importing
# shared modules). The write side lives in api/refresh.py.
_KV_LOCAL = os.path.join(tempfile.gettempdir(), "spy_kv_local.json")


def _kv_creds():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return url, token


def kv_get(key: str):
    url, token = _kv_creds()
    if url and token:
        req = urllib.request.Request(
            f"{url}/get/{key}", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()).get("result")
    if os.environ.get("VERCEL"):
        raise RuntimeError(
            "Vercel KV is not configured (set KV_REST_API_URL / KV_REST_API_TOKEN)"
        )
    # Local dev fallback: shared file store (see api/refresh.py).
    try:
        with open(_KV_LOCAL) as f:
            return json.load(f).get(key)
    except FileNotFoundError:
        return None


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authenticated(self.headers.get("Cookie")):
            return self._respond(401, {"error": "Not authenticated"})

        try:
            raw = kv_get(CACHE_KEY)
        except Exception as exc:  # noqa: BLE001
            return self._respond(502, {"error": str(exc)})

        if not raw:
            return self._respond(
                503, {"error": "No data cached yet. Trigger /api/refresh."}
            )

        cache = json.loads(raw)
        data = cache.get("data", {})
        refreshed_at = cache.get("refreshedAt")

        query = parse_qs(urlparse(self.path).query)
        symbol = query.get("symbol", [None])[0]

        if symbol:
            symbol = symbol.upper()
            if symbol not in data:
                return self._respond(404, {"error": f"No cached data for {symbol}"})
            return self._respond(
                200,
                {"symbol": symbol, "prices": data[symbol], "refreshedAt": refreshed_at},
            )

        # No symbol: report what's available.
        self._respond(
            200, {"symbols": sorted(data.keys()), "refreshedAt": refreshed_at}
        )

    def _respond(self, status: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
