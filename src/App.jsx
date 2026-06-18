import { useCallback, useEffect, useRef, useState } from 'react'
import Graph from './Graph.jsx'
import Login from './Login.jsx'

// Auto-refresh on load when the cache is older than this.
const STALE_MS = 5 * 60 * 1000

// Local dev runs against the IB-backed server (see api/refresh.py); there we
// poll for live prices. The production build serves Yahoo data and refreshes
// only on demand. import.meta.env.DEV is true exactly under `npm run dev`.
const LIVE = import.meta.env.DEV
const LIVE_INTERVAL_MS = 1000
// In live mode, poll the IB server's /health verdict on this cadence.
const HEALTH_INTERVAL_MS = 5000

// Server-computed graphs. Each endpoint returns { data: { label: [{time,value}] } }.
// Add a new backend graph here and it shows up automatically.
const GRAPHS = [
  {
    key: 'performance',
    endpoint: '/api/performance',
    title: 'Cumulative return — recent sessions',
    format: 'percent',
  },
  {
    key: 'rsi',
    endpoint: '/api/rsi',
    title: 'RSI (14) — last 10 sessions',
    format: 'rsi',
  },
  {
    key: 'p',
    endpoint: '/api/p',
    title: 'P RSI (14) — last 10 sessions',
    format: 'rsi',
  },
]

export default function App() {
  // authed: null = checking, false = needs login, true = logged in
  const [authed, setAuthed] = useState(null)
  const [symbols, setSymbols] = useState([])
  const [quotes, setQuotes] = useState({}) // ticker -> { price, prevClose, change, changePct }
  const [graphs, setGraphs] = useState({}) // key -> { label: [{time,value}] }
  const [refreshedAt, setRefreshedAt] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | empty | error
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [health, setHealth] = useState(null) // null until first poll; { state, summary, ... }
  const didLoad = useRef(false)

  // Push a {symbols, refreshedAt, quotes, graphs} payload into state. Updating
  // these triggers React to re-render the table + charts — no manual redraw.
  const applyData = useCallback((payload) => {
    const syms = payload.symbols ?? []
    setSymbols(syms)
    setRefreshedAt(payload.refreshedAt ?? null)
    setQuotes(payload.quotes ?? {})
    setGraphs(payload.graphs ?? {})
    setStatus(syms.length ? 'ready' : 'empty')
  }, [])

  // Refresh: the backend writes the prices, reads them back, and returns the
  // fresh index + every computed graph. We render straight from that response,
  // so we never read a stale CDN-cached GET right after a write.
  const refresh = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const res = await fetch('/api/refresh', { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `Refresh failed (${res.status})`)
      }
      applyData(await res.json())
    } catch (err) {
      setError(err.message)
    } finally {
      setRefreshing(false)
    }
  }, [applyData])

  // On load: read the cache's freshness, then auto-refresh if it's stale (or
  // missing). Otherwise load the existing graphs from their GET endpoints.
  const load = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch('/api/stock')
      if (res.status === 401) {
        setAuthed(false)
        return
      }
      setAuthed(true)
      const index =
        res.status === 503
          ? { symbols: [], refreshedAt: null }
          : await res.json()
      if (res.status !== 503 && !res.ok) throw new Error(`API returned ${res.status}`)

      const stale =
        !index.refreshedAt || Date.now() - index.refreshedAt * 1000 > STALE_MS
      if (stale) {
        await refresh()
        return
      }

      const results = await Promise.all(
        GRAPHS.map((g) =>
          fetch(g.endpoint)
            .then((r) => (r.ok ? r.json() : null))
            .catch(() => null) // tolerate a truncated/empty body — show the rest
        )
      )
      const next = {}
      GRAPHS.forEach((g, i) => {
        next[g.key] = results[i]?.data ?? {}
      })
      applyData({
        symbols: index.symbols,
        refreshedAt: index.refreshedAt,
        quotes: index.quotes,
        graphs: next,
      })
    } catch (err) {
      setAuthed(true)
      setStatus('error')
      setError(err.message)
    }
  }, [refresh, applyData])

  useEffect(() => {
    if (didLoad.current) return // guard StrictMode's double-invoke (avoid double auto-refresh)
    didLoad.current = true
    load()
  }, [load])

  // Live mode (local IB server): poll every second. We self-schedule the next
  // tick only after the previous refresh settles, so a slow fetch can't stack
  // overlapping requests — the cadence is "interval between refreshes".
  useEffect(() => {
    if (!LIVE || authed !== true) return
    let stopped = false
    let timer
    const tick = async () => {
      await refresh()
      if (!stopped) timer = setTimeout(tick, LIVE_INTERVAL_MS)
    }
    timer = setTimeout(tick, LIVE_INTERVAL_MS)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [authed, refresh])

  // Poll the IB server's health verdict every HEALTH_INTERVAL_MS (live mode
  // only). On any failure we treat the IB API as down so the badge goes red.
  useEffect(() => {
    if (!LIVE || authed !== true) return
    let stopped = false
    let timer
    const poll = async () => {
      try {
        const res = await fetch('/api/health')
        if (!res.ok) throw new Error(`health ${res.status}`)
        if (!stopped) setHealth(await res.json())
      } catch {
        if (!stopped) setHealth({ state: 'down', summary: 'Health check failed' })
      }
      if (!stopped) timer = setTimeout(poll, HEALTH_INTERVAL_MS)
    }
    poll()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [authed])

  async function handleLogout() {
    await fetch('/api/login', { method: 'DELETE' })
    setAuthed(false)
    setQuotes({})
    setGraphs({})
    setSymbols([])
  }

  if (authed === null) return <div className="status">Loading…</div>
  if (authed === false) return <Login onLogin={load} />

  return (
    <>
      <header>
        <h1>ETF Tracker</h1>
        {LIVE ? (
          <span className="live-badge" title="Auto-refreshing from the local IB server">
            <span className={`dot${refreshing ? ' busy' : ''}`} />
            Live
          </span>
        ) : (
          <button className="refresh" onClick={refresh} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh data'}
          </button>
        )}
        {LIVE && health && (
          <span
            className={`ib-health ${health.state || 'down'}`}
            title={[
              health.summary,
              health.failed?.length ? `Failing: ${health.failed.join(', ')}` : '',
            ]
              .filter(Boolean)
              .join('\n')}
          >
            <span className="dot" />
            {health.state === 'ok'
              ? 'IB OK'
              : health.state === 'degraded'
                ? 'IB degraded'
                : 'IB down'}
            {health.score != null && ` (${health.score})`}
          </span>
        )}
        <button className="logout" onClick={handleLogout}>
          Log out
        </button>
      </header>

      {refreshedAt && (
        <div className="meta">
          {LIVE ? (
            <>
              Auto-refreshing every {LIVE_INTERVAL_MS / 1000}s · last update{' '}
              {new Date(refreshedAt * 1000).toLocaleTimeString()}
            </>
          ) : (
            <>Last refreshed: {new Date(refreshedAt * 1000).toLocaleString()}</>
          )}
        </div>
      )}
      {error && <div className="status error">{error}</div>}
      {status === 'empty' && (
        <div className="status">No data cached yet — click “Refresh data”.</div>
      )}

      {symbols.length > 0 && (
        <section>
          <h2 className="section">Prices</h2>
          <table className="quotes">
            <thead>
              <tr>
                <th></th>
                {symbols.map((s) => (
                  <th key={s} className="sym">{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th>Price</th>
                {symbols.map((s) => {
                  const q = quotes[s] ?? {}
                  return (
                    <td key={s}>{q.price != null ? q.price.toFixed(2) : '—'}</td>
                  )
                })}
              </tr>
              <tr>
                <th>Change</th>
                {symbols.map((s) => {
                  const q = quotes[s] ?? {}
                  const dir = q.change > 0 ? 'up' : q.change < 0 ? 'down' : ''
                  const sign = q.change > 0 ? '+' : ''
                  return (
                    <td key={s} className={dir}>
                      {q.change != null ? `${sign}${q.change.toFixed(2)}` : '—'}
                    </td>
                  )
                })}
              </tr>
              <tr>
                <th>%</th>
                {symbols.map((s) => {
                  const q = quotes[s] ?? {}
                  const dir = q.change > 0 ? 'up' : q.change < 0 ? 'down' : ''
                  const sign = q.change > 0 ? '+' : ''
                  return (
                    <td key={s} className={dir}>
                      {q.changePct != null ? `${sign}${q.changePct.toFixed(2)}%` : '—'}
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </section>
      )}

      {GRAPHS.map((g) =>
        graphs[g.key] && Object.keys(graphs[g.key]).length > 0 ? (
          <section key={g.key}>
            <h2 className="section">{g.title}</h2>
            <Graph series={graphs[g.key]} format={g.format} />
          </section>
        ) : null
      )}
    </>
  )
}
