from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json

import yfinance as yf


def fetch_prices(symbol: str):
    """Return daily closing prices for the last month as a list of
    {date, close} dicts, oldest first."""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1mo", interval="1d")

    prices = []
    for ts, row in hist.iterrows():
        close = row.get("Close")
        if close is None:
            continue
        prices.append(
            {
                "date": ts.strftime("%Y-%m-%d"),
                "close": round(float(close), 2),
            }
        )
    return prices


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        symbol = query.get("symbol", ["SPY"])[0].upper()

        try:
            prices = fetch_prices(symbol)
            if not prices:
                raise ValueError(f"No price data returned for {symbol}")
            payload = {"symbol": symbol, "prices": prices}
            self._respond(200, payload)
        except Exception as exc:  # noqa: BLE001 - surface error to client
            self._respond(502, {"error": str(exc)})

    def _respond(self, status: int, body: dict):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
