from http.server import BaseHTTPRequestHandler
import json
import os
import hmac
import hashlib
import time
import urllib.request
import tempfile

import pandas as pd

CACHE_KEY = "prices"
PERF_WINDOW = 11  # df.iloc[-PERF_WINDOW:]


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
    """Convert a DataFrame (DatetimeIndex x ticker columns) into a
    JSON-serializable dict ready for lightweight-charts:

        {"XLK": [{"time": "2024-01-02", "value": 1.23}, ...], "TLT": [...]}

    A single-ticker Series is also accepted. NaN points are skipped."""
    if getattr(df, "ndim", 2) == 1:  # Series -> one-column frame
        df = df.to_frame()

    out = {}
    for col in df.columns:
        series = []
        for ts, value in df[col].items():
            if value is None or value != value:  # None or NaN
                continue
            stamp = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)
            series.append({"time": stamp, "value": round(float(value), 2)})
        out[str(col)] = series
    return out


# --- Vercel KV (Upstash Redis REST) read access ----------------------------
# Inlined per-function (Vercel's Python runtime is unreliable about importing
# shared modules). The write side lives in api/refresh.py.
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


def load_frame():
    """Rebuild the cached prices into a wide DataFrame (DatetimeIndex x ticker
    columns of Close prices) plus the cache's refreshedAt timestamp. This is the
    `df` your quant code operates on — same shape yfinance gives you."""
    raw = kv_get(CACHE_KEY)
    if not raw:
        return None, None
    cache = json.loads(raw)
    data = cache.get("data", {})  # {ticker: [{time, value}]}
    columns = {
        ticker: pd.Series({p["time"]: p["value"] for p in points})
        for ticker, points in data.items()
    }
    df = pd.DataFrame(columns)
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df, cache.get("refreshedAt")


def compute(df):
    """The graph. Paste quant code here; it gets `df` (Close prices, wide) and
    must return a DataFrame/Series with a DatetimeIndex to plot.

    Cumulative return over the last PERF_WINDOW sessions, in percent:
        df.iloc[-11:].pct_change().fillna(0).cumsum()
    """
    return df.iloc[-PERF_WINDOW:].pct_change().fillna(0).cumsum() * 100


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not is_authenticated(self.headers.get("Cookie")):
            return self._respond(401, {"error": "Not authenticated"})

        try:
            df, refreshed_at = load_frame()
        except Exception as exc:  # noqa: BLE001
            return self._respond(502, {"error": str(exc)})

        if df is None or df.empty:
            return self._respond(
                503, {"error": "No data cached yet. Trigger /api/refresh."}
            )

        result = compute(df)
        self._respond(
            200, {"data": df_to_json(result), "refreshedAt": refreshed_at}
        )

    def _respond(self, status: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
