import os
import sys
import time
from http.server import BaseHTTPRequestHandler

import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, df_to_json, kv_set, respond, CACHE_KEY  # noqa: E402

# The universe we cache. Add tickers here as you add graphs.
TICKERS = ["XLK", "TLT", "GLD", "SHY", "MDY", "XLV", "UUP", "XLP"]
PERIOD = "3y"        # how much history to pull from Yahoo
MAX_ROWS = 750       # cap rows stored per ticker (~3 trading years)


def build_cache() -> dict:
    closes = yf.download(TICKERS, period=PERIOD, progress=False)["Close"]
    return df_to_json(closes.tail(MAX_ROWS))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not authed(self):
            return respond(self, 401, {"error": "Not authenticated"})

        try:
            data = build_cache()
            payload = {"refreshedAt": int(time.time()), "data": data}
            kv_set(CACHE_KEY, payload)
        except Exception as exc:  # noqa: BLE001 - surface to client
            return respond(self, 502, {"error": str(exc)})

        rows = max((len(v) for v in data.values()), default=0)
        respond(self, 200, {
            "ok": True,
            "refreshedAt": payload["refreshedAt"],
            "symbols": sorted(data),
            "rows": rows,
        })
