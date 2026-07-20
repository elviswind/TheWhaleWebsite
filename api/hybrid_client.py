"""Local-dev market data: Yahoo history spliced with IB's live current day.

Drop-in for the bit of `yfinance` this site uses, same as ib_client:

    import hybrid_client as yf
    closes = yf.download(TICKERS, period="6mo", progress=False)["Close"]

IB's history is raw — it doesn't back-adjust for dividends or splits — so
returns computed from it drift away from the deployed (Yahoo-backed) numbers.
Yahoo's history *is* adjusted, but its last point lags the live market. So we
take every day but the current one from Yahoo, and let IB supply the current
day's row, which is unadjusted in both sources anyway (adjustment factors only
ever apply to days *before* an event).

Yahoo history is cached in-process because the dev UI refreshes every second and
that history only changes once a day; only the IB call is on the hot path.
"""
import os
import sys
import threading
import time

import pandas as pd
import yfinance as _yf

import ib_client

HISTORY_TTL = int(os.environ.get("YF_HISTORY_TTL", "600"))
LIVE_PERIOD = "5d"  # only the last row is used; the margin covers weekends

_lock = threading.Lock()
_history_cache = {}  # key -> (fetched_at, DataFrame)


def _multi(df, symbols):
    """Normalize to MultiIndex (Price x Ticker) columns — both sources return
    flat columns for a single ticker."""
    if df is None or getattr(df, "empty", True):
        return None
    if not isinstance(df.columns, pd.MultiIndex):
        df = pd.concat({symbols[0]: df}, axis=1).swaplevel(axis=1)
    df.columns = df.columns.set_names(["Price", "Ticker"])
    df.index = pd.to_datetime(df.index)
    return df.sort_index().sort_index(axis=1)


def _history(symbols, period, start, end, interval, timeout):
    key = (tuple(symbols), period, str(start), str(end), interval)
    now = time.time()
    with _lock:
        hit = _history_cache.get(key)
        if hit and now - hit[0] < HISTORY_TTL:
            return hit[1]

    df = _multi(_yf.download(symbols, period=period, start=start, end=end,
                             interval=interval, progress=False), symbols)
    if df is None:
        raise RuntimeError(f"Yahoo returned no history for {', '.join(symbols)}")
    with _lock:
        _history_cache[key] = (now, df)
    return df


def _live(symbols, interval, base_url, timeout):
    """The current day's row from IB, or None if IB has nothing to add."""
    try:
        df = _multi(ib_client.download(symbols, period=LIVE_PERIOD,
                                       interval=interval, base_url=base_url,
                                       timeout=timeout), symbols)
    except Exception as exc:  # noqa: BLE001 - dev convenience, keep serving
        print(f"  [hybrid] IB unavailable ({exc}); serving Yahoo history only",
              file=sys.stderr)
        return None
    return None if df is None else df.loc[[df.index.max()]]


def download(tickers, period=None, start=None, end=None, interval="1d",
             group_by="column", base_url=None, timeout=ib_client.TIMEOUT,
             **kwargs):
    """Mimics yfinance.download. Extra yfinance kwargs are accepted and ignored."""
    if isinstance(tickers, str):
        symbols = [t for t in tickers.replace(",", " ").split() if t]
    else:
        symbols = list(tickers)

    out = _history(symbols, period, start, end, interval, timeout)
    live = _live(symbols, interval, base_url, timeout)

    if live is not None:
        day = live.index.max()
        # Ignore a stale IB row (server behind / market not open yet): it can
        # only ever *be* or *extend past* Yahoo's last day, never precede it.
        if day >= out.index.max():
            row = live.loc[day].reindex(out.columns)
            if day in out.index:
                # Keep Yahoo's value for anything IB didn't quote.
                row = row.where(row.notna(), out.loc[day])
                out = out.drop(index=day)
            # concat, not in-place assignment: it promotes dtypes as needed
            # (Yahoo's Volume is int64, IB's is float).
            out = pd.concat([out, row.to_frame(day).T]).sort_index()

    if len(symbols) == 1 and group_by != "ticker":
        out = out.droplevel("Ticker", axis=1)
    elif group_by == "ticker":
        out = out.swaplevel("Price", "Ticker", axis=1).sort_index(axis=1)
    return out
