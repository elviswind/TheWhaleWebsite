import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, load_frame, df_to_json, respond  # noqa: E402

PERF_WINDOW = 4  # df.iloc[-PERF_WINDOW:]

def getp(df):
    pct = df.dropna().pct_change()
    f = pct.rolling(3).sum() + pct
    f = f.dropna()
    choice = f.idxmin(axis=1)
    p = pct.shift(-1).loc[choice.index].apply(lambda row: row[choice[row.name]], axis=1)
    return p, choice

def rsi(returns, n=14):
    eq = (1 + returns).cumprod().dropna()
    delta = eq.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + gain / (loss + 1e-12)))


def compute(df):
    p, _ = getp(df.iloc[-60:][['MDY','GLD','SHY','TLT','XLK','XLV']])
    return rsi(p.shift(1)).iloc[-10:]

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
