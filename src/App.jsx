import { useCallback, useEffect, useRef, useState } from 'react'
import Graph from './Graph.jsx'
import Login from './Login.jsx'

// Auto-refresh on load when the cache is older than this.
const STALE_MS = 5 * 60 * 1000

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
  const [symbol, setSymbol] = useState(null)
  const [priceData, setPriceData] = useState({}) // ticker -> [{time,value}]
  const [graphs, setGraphs] = useState({}) // key -> { label: [{time,value}] }
  const [refreshedAt, setRefreshedAt] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | empty | error
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const didLoad = useRef(false)

  // Push a {symbols, refreshedAt, graphs, prices?} payload into state. Updating
  // these triggers React to re-render the charts — no manual redraw needed.
  const applyData = useCallback((payload) => {
    const syms = payload.symbols ?? []
    setSymbols(syms)
    setRefreshedAt(payload.refreshedAt ?? null)
    setGraphs(payload.graphs ?? {})
    if (payload.prices) setPriceData(payload.prices)
    setSymbol((cur) => (cur && syms.includes(cur) ? cur : syms[0] ?? null))
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
        GRAPHS.map((g) => fetch(g.endpoint).then((r) => (r.ok ? r.json() : null)))
      )
      const next = {}
      GRAPHS.forEach((g, i) => {
        next[g.key] = results[i]?.data ?? {}
      })
      applyData({ symbols: index.symbols, refreshedAt: index.refreshedAt, graphs: next })
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

  // Fetch the selected symbol's prices on demand — unless a refresh already
  // populated the full price set (every ticker), in which case we have it.
  useEffect(() => {
    if (!symbol || priceData[symbol]) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`/api/stock?symbol=${symbol}`)
        if (!res.ok) throw new Error(`API returned ${res.status}`)
        const json = await res.json()
        if (!cancelled) setPriceData((d) => ({ ...d, [symbol]: json.prices }))
      } catch (err) {
        if (!cancelled) {
          setStatus('error')
          setError(err.message)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [symbol, priceData])

  async function handleLogout() {
    await fetch('/api/login', { method: 'DELETE' })
    setAuthed(false)
    setPriceData({})
    setGraphs({})
    setSymbols([])
  }

  const prices = (symbol && priceData[symbol]) || []

  if (authed === null) return <div className="status">Loading…</div>
  if (authed === false) return <Login onLogin={load} />

  return (
    <>
      <header>
        <h1>ETF Tracker</h1>
        {symbols.length > 0 && (
          <select value={symbol ?? ''} onChange={(e) => setSymbol(e.target.value)}>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
        <button className="refresh" onClick={refresh} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh data'}
        </button>
        <button className="logout" onClick={handleLogout}>
          Log out
        </button>
      </header>

      {refreshedAt && (
        <div className="meta">
          Last refreshed: {new Date(refreshedAt * 1000).toLocaleString()}
        </div>
      )}
      {error && <div className="status error">{error}</div>}
      {status === 'empty' && (
        <div className="status">No data cached yet — click “Refresh data”.</div>
      )}

      {prices.length > 0 && symbol && (
        <section>
          <h2 className="section">{symbol} — price</h2>
          <Graph series={{ [symbol]: prices }} format="price" />
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
