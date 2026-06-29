import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, load_frame, df_to_json, respond  # noqa: E402

def compute(df):
    x = df[['MDY','GLD','SHY','TLT','XLK','XLV']].iloc[-4:].pct_change().fillna(0)
    x.iloc[-1] *= 2
    return x.cumsum() * 100

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
