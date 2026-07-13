"""Every computed metric, behind one endpoint.

    GET /api/metrics             -> all metrics
    GET /api/metrics?m=CASH      -> just CASH
    GET /api/metrics?m=UUP+P1,XLP -> just those two

Response: {"metrics": {key: {label: [{time, value}]}}, "refreshedAt": ts}

To add a metric: write a function that takes the price frame and returns a
DataFrame (or Series), decorate it with @metric("key"), and add the key to
GRAPHS in src/App.jsx. It is then served here and included in /api/refresh
automatically — no new file, no route, no wiring.

Any ticker a metric reads must be in TICKERS in refresh.py.
"""
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

sys.path.insert(0, os.path.dirname(__file__))
from _common import authed, load_frame, df_to_json, respond, getp, rsi  # noqa: E402

# key -> compute(df). Ordered by insertion, so /api/metrics returns them in the
# order they're defined below.
METRICS = {}


def metric(key):
    def register(fn):
        METRICS[key] = fn
        return fn
    return register


# --- Helpers ---------------------------------------------------------------
def zscore(x, w, fill=0.0):
    sd = x.rolling(w).std()
    return ((x - x.rolling(w).mean()) / sd).where(sd != 0, fill)


def safediv(num, den, fill=0.0):
    return (num / den).where(den != 0, fill)


# The rotation universe `getp` picks from.
PICKS = ['MDY', 'GLD', 'SHY', 'TLT', 'XLK', 'XLV']


# --- Metrics ---------------------------------------------------------------
@metric("performance")
def performance(df):
    x = df[PICKS].iloc[-4:].pct_change().fillna(0)
    x.iloc[-1] *= 2
    return x.cumsum() * 100


@metric("rsi")
def rsi_all(df):
    return rsi(df.iloc[-60:].dropna().pct_change()).iloc[-10:]


@metric("p")
def p(df):
    picked, _, _ = getp(df.iloc[-60:][PICKS])
    return rsi(picked.shift(1)).iloc[-10:]

@metric("pt")
def pt(df):
    _, _, f = getp(df.iloc[-60:][PICKS])
    return f * 100

@metric("F2")
def f_dur(df):
    s = df[['SHY','SPYG','TIP','UUP','XLK','XLP']]
    return (s.pct_change().clip(upper=0).rolling(6).std() / (s.pct_change().clip(lower=0).rolling(6).std()+ 0.00001)).iloc[-10:] * 1000

@metric("F3")
def f_sharpe(df):
    s = df[['IEF','TIP','TLT','XLK','XLP','XLV']]
    return (s.pct_change().rolling(6).mean() / (s.pct_change().rolling(6).std() + 0.00001)).iloc[-10:] * 1000

@metric("F4")
def f_zprice(df):
    s = df[['IEF','SHY','TIP','TLT','XLP','XLV']]
    return ((s - s.rolling(15).mean()) / s.rolling(15).std()).iloc[-10:] * 1000


# --- Compute ---------------------------------------------------------------
def compute_all(df, keys=None) -> dict:
    """Compute `keys` (default: every metric) from the price frame. A failing
    metric yields {} rather than sinking the whole response — the frontend
    already tolerates a missing graph."""
    out = {}
    for key in keys or METRICS:
        try:
            out[key] = df_to_json(METRICS[key](df))
        except Exception:  # noqa: BLE001
            out[key] = {}
    return out


def _requested(query: str) -> list:
    """Metric keys from a `?m=a,b` query string, in the order given.

    Decoded with unquote, not parse_qs: most keys contain a literal '+'
    (UUP+P1), and parse_qs would form-decode it into a space. Both `?m=UUP+P1`
    and the strictly-correct `?m=UUP%2BP1` therefore resolve."""
    out = []
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if unquote(name) == "m":
            out += [k for k in unquote(value).split(",") if k]
    return out


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not authed(self):
            return respond(self, 401, {"error": "Not authenticated"})

        requested = _requested(urlparse(self.path).query)
        unknown = [k for k in requested if k not in METRICS]
        if unknown:
            return respond(self, 400, {"error": f"Unknown metric: {', '.join(unknown)}"})

        try:
            df, refreshed_at = load_frame()
        except Exception as exc:  # noqa: BLE001
            return respond(self, 502, {"error": str(exc)})
        if df is None or df.empty:
            return respond(self, 503, {"error": "No data cached yet. Trigger /api/refresh."})

        respond(self, 200, {
            "metrics": compute_all(df, requested or None),
            "refreshedAt": refreshed_at,
        }, cache=True)
