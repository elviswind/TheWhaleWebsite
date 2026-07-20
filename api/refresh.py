import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
# Market-data source: Yahoo Finance when deployed (Vercel sets VERCEL=1). In dev
# it's hybrid_client — Yahoo's dividend/split-adjusted history with the current
# day's live row from the local IB server (set IB_API_URL). Both mirror
# yfinance's download() shape, so the rest of this file is identical either way.
if os.environ.get("VERCEL"):
    import yfinance as yf  # noqa: E402
else:
    import hybrid_client as yf  # noqa: E402
from _common import (  # noqa: E402
    authed, df_to_json, kv_lock, kv_set, kv_unlock, load_cache, load_frame,
    quotes_from_data, respond, CACHE_KEY,
)

# Reuse the metric registry so the data returned by refresh matches exactly what
# GET /api/metrics would produce.
from metrics import compute_all  # noqa: E402

# The universe we cache. Add tickers here as you add metrics.
TICKERS = ["XLK", "TLT", "GLD", "SHY", "MDY", "XLV", "UUP", "XLP", "DBC", "SPY", "IEF", "TIP", "SPYG"]
PERIOD = "6mo"       # how much history to pull from Yahoo
MAX_ROWS = 130       # cap rows stored per ticker (~6 trading months)

LOCK_KEY = "prices:lock"     # single-writer lock so concurrent refreshes don't all hit Yahoo
# Local IB-backed dev refreshes aggressively (the UI polls every second); the
# deployed Yahoo path stays gently rate-limited so we don't hammer the API.
LIVE = not os.environ.get("VERCEL")
RATE_LIMIT_SECONDS = 0 if LIVE else 60  # skip the fetch if the cache was refreshed this recently
LOCK_WAIT_SECONDS = 10       # how long a lock-loser waits for the winner's write to land


def build_cache() -> dict:
    closes = yf.download(TICKERS, period=PERIOD, progress=False)["Close"]
    return df_to_json(closes.tail(MAX_ROWS))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authed(self):
            return respond(self, 401, {"error": "Not authenticated"})

        try:
            maybe_refresh()
            # Read the (now-current) cache straight back so the response carries
            # the same freshness/data the GET endpoints would serve — no waiting
            # on a CDN-cached round trip.
            df, refreshed_at = load_frame()
        except Exception as exc:  # noqa: BLE001 - surface to client
            return respond(self, 502, {"error": str(exc)})

        if df is None or df.empty:
            return respond(self, 503, {"error": "No data available."})

        prices = df_to_json(df)
        respond(self, 200, {
            "ok": True,
            "refreshedAt": refreshed_at,
            "symbols": sorted(prices),
            "quotes": quotes_from_data(prices),
            "graphs": compute_all(df),
        })


def maybe_refresh():
    """Refresh the cache if it's stale, coordinating with concurrent calls:

    1. read current; skip the fetch if refreshed < RATE_LIMIT_SECONDS ago
    2. take the single-writer lock; if we can't, briefly wait for the holder
    3. fetch from Yahoo
    4. write, then release the lock

    Either way the caller reads the resulting cache back and returns it, so a
    request that loses the race still serves fresh data instead of erroring.
    """
    cache = load_cache()
    now = int(time.time())
    if cache and now - (cache.get("refreshedAt") or 0) < RATE_LIMIT_SECONDS:
        return  # already fresh — serve it as-is

    prev = cache.get("refreshedAt") if cache else None
    if not kv_lock(LOCK_KEY):
        # Another request is already fetching. Wait briefly for its write so
        # we return fresh data rather than the stale cache.
        deadline = time.time() + LOCK_WAIT_SECONDS
        while time.time() < deadline:
            time.sleep(0.5)
            cache = load_cache()
            if cache and cache.get("refreshedAt") != prev:
                return
        return  # timed out — fall back to whatever's current

    try:
        data = build_cache()
        kv_set(CACHE_KEY, {"refreshedAt": now, "data": data})
    finally:
        kv_unlock(LOCK_KEY)
