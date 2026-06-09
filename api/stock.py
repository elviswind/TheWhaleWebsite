import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, load_cache, respond  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authed(self):
            return respond(self, 401, {"error": "Not authenticated"})
        try:
            cache = load_cache()
        except Exception as exc:  # noqa: BLE001
            return respond(self, 502, {"error": str(exc)})
        if not cache:
            return respond(self, 503, {"error": "No data cached yet. Trigger /api/refresh."})

        data = cache.get("data", {})
        refreshed_at = cache.get("refreshedAt")
        symbol = parse_qs(urlparse(self.path).query).get("symbol", [None])[0]

        if symbol:
            symbol = symbol.upper()
            if symbol not in data:
                return respond(self, 404, {"error": f"No cached data for {symbol}"})
            return respond(
                self, 200,
                {"symbol": symbol, "prices": data[symbol], "refreshedAt": refreshed_at},
                cache=True,
            )

        # No symbol: report what's available.
        respond(self, 200, {"symbols": sorted(data), "refreshedAt": refreshed_at}, cache=True)
