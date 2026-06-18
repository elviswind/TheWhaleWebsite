"""Drop-in replacement for the bit of `yfinance` this site uses.

Talks to the IB-backed price server (D:/FIRE/fastapi) over HTTP and returns the
same DataFrame shape yfinance gives, so existing code keeps working:

    import ib_client as yf
    closes = yf.download(TICKERS, period="6mo", progress=False)["Close"].tail(130)

Portability: stdlib `urllib` only (no `requests`), pandas required (already a
dependency). Parquet transport is used automatically when `pyarrow` is
installed; otherwise it falls back to JSON, so this file + pandas is all you
need on the website machine.

Point it at the server with the IB_API_URL env var, e.g.
    IB_API_URL=http://192.168.1.50:8198
Defaults to http://localhost:8198.
"""
import io
import json
import os
import urllib.parse
import urllib.request

import pandas as pd

BASE_URL = os.environ.get("IB_API_URL", "http://192.168.1.19:8198")
TIMEOUT = 30

try:
    import pyarrow  # noqa: F401
    _HAVE_PARQUET = True
except Exception:
    _HAVE_PARQUET = False

_FIELD = {"open": "Open", "high": "High", "low": "Low",
          "close": "Close", "volume": "Volume"}


def download(tickers, period=None, start=None, end=None, interval="1d",
             group_by="column", base_url=None, timeout=TIMEOUT, **kwargs):
    """Mimics yfinance.download. Extra yfinance kwargs (progress, auto_adjust,
    threads, ...) are accepted and ignored.

    Returns a DataFrame with MultiIndex columns (Price x Ticker) and a tz-naive
    DatetimeIndex; a single ticker yields flat columns — exactly like yfinance.
    """
    if isinstance(tickers, str):
        symbols = [t for t in tickers.replace(",", " ").split() if t]
    else:
        symbols = list(tickers)

    params = {
        "tickers": ",".join(symbols),
        "interval": interval,
        "fmt": "parquet" if _HAVE_PARQUET else "json",
    }
    if period:
        params["period"] = period
    if start is not None:
        params["start"] = str(start)
    if end is not None:
        params["end"] = str(end)

    url = f"{base_url or BASE_URL}/download?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"download failed ({e.code}): {e.read().decode(errors='replace')}")

    if _HAVE_PARQUET:
        tidy = pd.read_parquet(io.BytesIO(body))
    else:
        tidy = pd.DataFrame(json.loads(body.decode("utf-8")))

    if tidy.empty:
        return pd.DataFrame()

    tidy["date"] = pd.to_datetime(tidy["date"])
    wide = tidy.pivot(index="date", columns="ticker",
                      values=["open", "high", "low", "close", "volume"])
    wide = wide.rename(columns=_FIELD, level=0)
    wide.columns = wide.columns.set_names(["Price", "Ticker"])
    wide = wide.sort_index()
    wide.index.name = "Date"

    if len(symbols) == 1 and group_by != "ticker":
        wide = wide.droplevel("Ticker", axis=1)
    elif group_by == "ticker":
        wide = wide.swaplevel("Price", "Ticker", axis=1).sort_index(axis=1)

    return wide
