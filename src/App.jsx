import { useCallback, useEffect, useState } from 'react'
import Chart from './Chart.jsx'
import PerfChart from './PerfChart.jsx'
import Login from './Login.jsx'

export default function App() {
  // authed: null = checking, false = needs login, true = logged in
  const [authed, setAuthed] = useState(null)
  const [symbols, setSymbols] = useState([])
  const [symbol, setSymbol] = useState(null)
  const [prices, setPrices] = useState([])
  const [performance, setPerformance] = useState({}) // computed server-side
  const [refreshedAt, setRefreshedAt] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | empty | error
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  // Load the list of cached symbols + the computed performance series.
  // No math here — the backend does it (see api/performance.py).
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
        setPerformance({})
        setStatus('empty')
        return
      }
      if (!res.ok) throw new Error(`API returned ${res.status}`)
      const json = await res.json()
      setSymbols(json.symbols)
      setRefreshedAt(json.refreshedAt)
      setSymbol((cur) => (cur && json.symbols.includes(cur) ? cur : json.symbols[0]))
      setStatus('ready')

      const perfRes = await fetch('/api/performance')
      setPerformance(perfRes.ok ? (await perfRes.json()).data : {})
    } catch (err) {
      setAuthed(true)
      setStatus('error')
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    loadIndex()
  }, [loadIndex])

  // Load the selected symbol's series whenever it changes.
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
    setPerformance({})
    setSymbols([])
  }

  if (authed === null) return <div className="status">Loading…</div>
  if (authed === false) return <Login onLogin={loadIndex} />

  const latest = prices.length ? prices[prices.length - 1].value : null

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
        {latest != null && <span className="price">${latest.toFixed(2)}</span>}
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
      {prices.length > 0 && <Chart prices={prices} />}

      {Object.keys(performance).length > 0 && (
        <>
          <h2 className="section">Cumulative return — recent sessions</h2>
          <PerfChart series={performance} />
        </>
      )}
    </>
  )
}
