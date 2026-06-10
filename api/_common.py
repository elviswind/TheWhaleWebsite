"""Shared helpers for the api/ serverless functions.

Imported by each function via an explicit sys.path insert (see the top of
stock.py / refresh.py / performance.py / login.py) so it resolves regardless of
Vercel's working directory. The imports are static `from _common import ...`
statements so Vercel's bundler traces this file and ships it with each function.
"""
import json
import os
import hmac
import hashlib
import time
import tempfile
import urllib.request

CACHE_KEY = "prices"
SESSION_TTL = 60 * 60 * 24  # 24 hours


# --- Auth (signed HttpOnly session cookie) ---------------------------------
def _sign(exp: str) -> str:
    """HMAC the expiry using the configured password as the key, so changing
    the password invalidates every outstanding session — no extra secret."""
    key = (os.environ.get("APP_PASSWORD") or "").strip().encode()
    return hmac.new(key, exp.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    return f"{exp}.{_sign(exp)}"


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
    return hmac.compare_digest(sig, _sign(exp))


def authed(handler) -> bool:
    """Convenience: validate the cookie on a BaseHTTPRequestHandler."""
    return is_authenticated(handler.headers.get("Cookie"))


# --- JSON responses --------------------------------------------------------
def respond(handler, status: int, body: dict, extra_headers=None, cache=False):
    data = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    if cache:
        handler.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate")
    for key, value in extra_headers or []:
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


# --- Chart serialization ---------------------------------------------------
def df_to_json(df) -> dict:
    """Convert a DataFrame (DatetimeIndex x ticker columns) into a
    JSON-serializable dict ready for lightweight-charts:

        {"XLK": [{"time": "2024-01-02", "value": 187.34}, ...], "TLT": [...]}

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


# --- Vercel KV (Upstash Redis REST) ----------------------------------------
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
    try:  # Local dev fallback: shared file store.
        with open(_KV_LOCAL) as f:
            return json.load(f).get(key)
    except FileNotFoundError:
        return None


def kv_set(key: str, value):
    if not isinstance(value, str):
        value = json.dumps(value)
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
    store = {}  # Local dev fallback: shared file store.
    try:
        with open(_KV_LOCAL) as f:
            store = json.load(f)
    except FileNotFoundError:
        pass
    store[key] = value
    with open(_KV_LOCAL, "w") as f:
        json.dump(store, f)


def kv_command(*args):
    """Run a raw Redis command via the Upstash REST API and return its `result`.
    Returns None when KV isn't configured (local dev has no real concurrency)."""
    url, token = _kv_creds()
    if not (url and token):
        return None
    req = urllib.request.Request(
        url,
        data=json.dumps([str(a) for a in args]).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode()).get("result")


def kv_lock(key: str, ttl: int = 120) -> bool:
    """Best-effort single-writer lock: SET key <ts> NX EX ttl. True if acquired.
    The TTL means the lock frees itself if its holder dies mid-refresh. Without
    KV (local dev) there's no concurrency to guard, so it always succeeds."""
    url, token = _kv_creds()
    if not (url and token):
        return True
    return kv_command("SET", key, int(time.time()), "NX", "EX", ttl) == "OK"


def kv_unlock(key: str):
    """Release a kv_lock. No-op when KV isn't configured."""
    url, token = _kv_creds()
    if url and token:
        kv_command("DEL", key)


# --- Cached prices ---------------------------------------------------------
def load_cache():
    """Return the parsed price cache `{refreshedAt, data}` or None if empty."""
    raw = kv_get(CACHE_KEY)
    return json.loads(raw) if raw else None


def load_frame():
    """Rebuild the cached prices into a wide DataFrame (DatetimeIndex x ticker
    columns of Close prices) plus the cache's refreshedAt timestamp — the `df`
    your quant code operates on, same shape yfinance gives you."""
    import pandas as pd  # lazy: only graph endpoints need pandas

    cache = load_cache()
    if not cache:
        return None, None
    data = cache.get("data", {})  # {ticker: [{time, value}]}
    columns = {
        ticker: pd.Series({p["time"]: p["value"] for p in points})
        for ticker, points in data.items()
    }
    df = pd.DataFrame(columns)
    df.index = pd.to_datetime(df.index)
    return df.sort_index(), cache.get("refreshedAt")


# --- Quant libs
def rsi(returns, n=14):
    eq = (1 + returns.fillna(0)).cumprod()
    delta = eq.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + gain / (loss + 1e-12)))

def getp(df):
    pct = df.dropna().pct_change()
    f = pct.rolling(3).sum() + pct
    f = f.dropna()
    choice = f.idxmin(axis=1)
    p = pct.shift(-1).loc[choice.index].apply(lambda row: row[choice[row.name]], axis=1)
    return p, choice