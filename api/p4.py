import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, load_frame, df_to_json, respond, getp, rsi  # noqa: E402

def safediv(num, den, fill=0.0):
    return (num / den).where(den != 0, fill)

def compute(df):
    #CASH
    s = df[['SPY', 'TLT', 'GLD', 'DBC']]
    return safediv(s.pct_change().rolling(7).skew(), s.pct_change().rolling(7).skew().rolling(7).std()).iloc[-10:]

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authed(self):
            return respond(self, 401, {"error": "Not authenticated"})
        try:
            df, refreshed_at = load_frame()
        except Exception as exc:  # noqa: BLE001
            return respond(self, 502, {"error": str(exc)})
        if df is None or df.empty:
            return respond(self, 503, {"error": "No data cached yet. Trigger /api/refresh."})
        respond(self, 200, {"data": df_to_json(compute(df)), "refreshedAt": refreshed_at}, cache=True)
