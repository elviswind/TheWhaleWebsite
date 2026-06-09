# SPY Tracker

A small Vercel app: a **Vite + React** SPA that fetches SPY price history from a
**Python serverless function** (which pulls data from Yahoo Finance) and renders
it as a line chart with [lightweight-charts](https://github.com/tradingview/lightweight-charts).

## Layout

```
api/stock.py          Python serverless function — GET /api/stock?symbol=SPY (auth-protected)
api/login.py          POST = log in (sets cookie), DELETE = log out
api/requirements.txt  Python deps (yfinance)
src/                  React SPA (Login + Chart)
index.html            SPA entry
```

## Authentication

The API is protected by a single configurable username/password (no signup).
`/api/login` validates them against env vars and sets a signed, HttpOnly
session cookie (24h); `/api/stock` rejects any request without a valid cookie.
The cookie is signed with the password as the key, so changing the password
invalidates all existing sessions.

Set these env vars in the Vercel dashboard (Project → Settings → Environment
Variables) and, for local dev, in `.env.local` (see `.env.example`):

```
APP_USERNAME=...
APP_PASSWORD=...   # use a long random value
```

If they are unset, the API fails closed (401 / 503).

## Local development

The frontend and the Python function run together under the Vercel CLI:

```bash
npm install
npm i -g vercel        # if you don't have it
vercel dev             # serves SPA + /api on http://localhost:3000
```

Alternatively, run the SPA alone with hot reload:

```bash
vercel dev             # terminal 1 — provides /api on :3000
npm run dev            # terminal 2 — Vite on :5173, proxies /api to :3000
```

## Deploy

```bash
vercel        # preview
vercel --prod # production
```

Vercel auto-detects Vite (build → `dist/`) and the Python function in `api/`.

## API

`GET /api/stock?symbol=SPY` (requires the auth cookie; `401` otherwise) →

```json
{
  "symbol": "SPY",
  "prices": [{ "date": "2026-05-12", "close": 521.34 }, ...]
}
```