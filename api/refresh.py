from http.server import BaseHTTPRequestHandler
import json
import os
import hmac
import hashlib
import time
import urllib.request
import tempfile

import yfinance as yf

# The universe we cache. Add tickers here as you add graphs.
TICKERS = ["XLK", "TLT", "GLD", "SHY", "MDY", "XLV", "UUP", "XLP"]
PERIOD = "3y"        # how much history to pull from Yahoo
MAX_ROWS = 750       # cap rows stored per ticker (~3 trading years)
CACHE_KEY = "prices"


def is_authenticated(cookie_header: str) -> bool:
    """Validate the signed `auth` session cookie set by /api/login."""
    password = (os.environ.get("APP_PASSWORD") or "").strip()
    if not password:
        return False

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


def df_to_json(df):
    """Convert a Close-price DataFrame (DatetimeIndex x ticker columns) into a
    JSON-serializable dict ready for lightweight-charts:

        {"XLK": [{"time": "2024-01-02", "value": 187.34}, ...], "TLT": [...]}

    A single-ticker Series is also accepted. NaN points are skipped so each
    series only contains real data."""
    if getattr(df, "ndim", 2) == 1:  # Series -> one-column frame
        df = df.to_frame()

    out = {}
    for col in df.columns:
        series = []
        for ts, value in df[col].items():
            if value is None or value != value:  # None or NaN
                continue
            series.append(
                {"time": ts.strftime("%Y-%m-%d"), "value": round(float(value), 2)}
            )
        out[str(col)] = series
    return out


# --- Vercel KV (Upstash Redis REST) write access ---------------------------
_KV_LOCAL = os.path.join(tempfile.gettempdir(), "spy_kv_local.json")


def _env_endswith(suffix: str):
    """Value of an env var named exactly `suffix`, or ending with it. Vercel KV
    stores prefix their vars (e.g. TheWhaleWebsite_KV_REST_API_URL), so we match
    on the suffix to stay prefix-agnostic."""
    if os.environ.get(suffix):
        return os.environ[suffix]
    for key, val in os.environ.items():
        if val and key.endswith(suffix):
            return val
    return None


def _kv_creds():
    url = _env_endswith("KV_REST_API_URL") or _env_endswith("UPSTASH_REDIS_REST_URL")
    token = _env_endswith("KV_REST_API_TOKEN") or _env_endswith("UPSTASH_REDIS_REST_TOKEN")
    return url, token


def kv_set(key: str, value: str):
    url, token = _kv_creds()
    if url and token:
        req = urllib.request.Request(
            f"{url}/set/{key}",
            data=value.encode(),
            headers={"Authorization": f"Bearer {token}"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15).read()
        return
    if os.environ.get("VERCEL"):
        raise RuntimeError(
            "Vercel KV is not configured (set KV_REST_API_URL / KV_REST_API_TOKEN)"
        )
    # Local dev fallback: shared file store, read by api/stock.py.
    store = {}
    try:
        with open(_KV_LOCAL) as f:
            store = json.load(f)
    except FileNotFoundError:
        pass
    store[key] = value
    with open(_KV_LOCAL, "w") as f:
        json.dump(store, f)


def build_cache() -> dict:
    closes = yf.download(TICKERS, period=PERIOD, progress=False)["Close"]
    closes = closes.tail(MAX_ROWS)
    return df_to_json(closes)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not is_authenticated(self.headers.get("Cookie")):
            return self._json(401, {"error": "Not authenticated"})

        try:
            data = build_cache()
            payload = {"refreshedAt": int(time.time()), "data": data}
            kv_set(CACHE_KEY, json.dumps(payload))
        except Exception as exc:  # noqa: BLE001 - surface to client
            return self._json(502, {"error": str(exc)})

        rows = max((len(v) for v in data.values()), default=0)
        self._json(
            200,
            {
                "ok": True,
                "refreshedAt": payload["refreshedAt"],
                "symbols": sorted(data.keys()),
                "rows": rows,
            },
        )

    def _json(self, status: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
