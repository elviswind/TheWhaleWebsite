import { useCallback, useEffect, useState } from 'react'
import Graph from './Graph.jsx'
import Login from './Login.jsx'

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
  const [prices, setPrices] = useState([])
  const [graphs, setGraphs] = useState({}) // key -> { label: [{time,value}] }
  const [refreshedAt, setRefreshedAt] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | empty | error
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // Load the symbol list + every computed graph. No math here — the backend
  // does it (see api/performance.py, api/rsi.py).
  const loadIndex = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch('/api/stock')
      if (res.status === 401) {
        setAuthed(false)
        return
      }
      setAuthed(true)
      if (res.status === 503) {
        setSymbols([])
        setGraphs({})
        setStatus('empty')
        return
      }
      if (!res.ok) throw new Error(`API returned ${res.status}`)
      const json = await res.json()
      setSymbols(json.symbols)
      setRefreshedAt(json.refreshedAt)
      setSymbol((cur) => (cur && json.symbols.includes(cur) ? cur : json.symbols[0]))
      setStatus('ready')

      const results = await Promise.all(
        GRAPHS.map((g) => fetch(g.endpoint).then((r) => (r.ok ? r.json() : null)))
      )
      const next = {}
      GRAPHS.forEach((g, i) => {
        next[g.key] = results[i]?.data ?? {}
      })
      setGraphs(next)
    } catch (err) {
      setAuthed(true)
      setStatus('error')
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    loadIndex()
  }, [loadIndex])

  // Load the selected symbol's price series whenever it changes.
  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`/api/stock?symbol=${symbol}`)
        if (!res.ok) throw new Error(`API returned ${res.status}`)
        const json = await res.json()
        if (!cancelled) setPrices(json.prices)
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
  }, [symbol])

  async function handleRefresh() {
    setRefreshing(true)
    setError(null)
    try {
      const res = await fetch('/api/refresh', { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `Refresh failed (${res.status})`)
      }
      await loadIndex()
    } catch (err) {
      setError(err.message)
    } finally {
      setRefreshing(false)
    }
  }

  async function handleLogout() {
    await fetch('/api/login', { method: 'DELETE' })
    setAuthed(false)
    setPrices([])
    setGraphs({})
    setSymbols([])
  }

  if (authed === null) return <div className="status">Loading…</div>
  if (authed === false) return <Login onLogin={loadIndex} />

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
        <button className="refresh" onClick={handleRefresh} disabled={refreshing}>
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
