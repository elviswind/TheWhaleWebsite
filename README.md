# ETF Tracker

A small Vercel app: a **Vite + React** SPA that charts ETF closing prices with
[lightweight-charts](https://github.com/tradingview/lightweight-charts), backed
by **Python serverless functions**.

To avoid hammering Yahoo Finance, data is fetched **only** by an explicit,
user-triggered refresh and stored in **Vercel KV**. All read endpoints serve
from that cache and never call Yahoo directly.

## Layout

```
api/refresh.py        POST — pulls 3y of closes for the tickers, caps at 750
                      rows, writes them to Vercel KV (the only Yahoo caller)
api/stock.py          GET  — reads the KV cache; ?symbol=XLK → that series,
                      no symbol → list of cached symbols
api/login.py          POST = log in (sets cookie), DELETE = log out
api/requirements.txt  Python deps (yfinance)
src/                  React SPA (Login, symbol selector, Refresh button, Chart)
```

Tickers are defined in `api/refresh.py` (`TICKERS`). Add to that list to track more.

## Data flow

1. User clicks **Refresh data** → `POST /api/refresh`.
2. `refresh.py` downloads `Close` prices (3y) for all tickers, trims to the last
   750 rows, and stores `{"refreshedAt", "data": {ticker: [{time, value}]}}` in KV.
3. The SPA reads `GET /api/stock` for the symbol list and
   `GET /api/stock?symbol=XLK` for each series, then charts it.

## Auth

Single configurable user (no signup). `/api/login` validates credentials and
sets a signed, HttpOnly session cookie; every endpoint rejects requests without
a valid cookie.

## Environment variables (Vercel → Settings → Environment Variables)

| Var | Purpose |
| --- | --- |
| `APP_USERNAME`, `APP_PASSWORD` | Login credentials (set as **non-sensitive**) |
| `KV_REST_API_URL`, `KV_REST_API_TOKEN` | Auto-injected when you connect a Vercel KV / Upstash Redis store to the project |

The code also accepts `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`.
Without KV configured, the API fails closed (the read endpoint reports no data,
refresh errors).

## API

`POST /api/refresh` → `{ "ok": true, "refreshedAt": <epoch>, "symbols": [...], "rows": 750 }`

`GET /api/stock?symbol=XLK` →
```json
{ "symbol": "XLK", "prices": [{ "time": "2024-01-02", "value": 187.34 }, ...], "refreshedAt": 1781041307 }
```

`GET /api/stock` → `{ "symbols": ["GLD", "MDY", ...], "refreshedAt": 1781041307 }`

## Deploy

```bash
vercel --prod
```

Vercel auto-detects Vite (build → `dist/`) and the Python functions in `api/`.
Connect a Vercel KV store to the project first, then run a refresh once after
deploy to populate the cache.
