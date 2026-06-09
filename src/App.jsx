import { useCallback, useEffect, useState } from 'react'
import Chart from './Chart.jsx'
import Login from './Login.jsx'

export default function App() {
  // authed: null = unknown/checking, false = needs login, true = logged in
  const [authed, setAuthed] = useState(null)
  const [prices, setPrices] = useState([])
  const [error, setError] = useState(null)

  const loadStock = useCallback(async () => {
    setError(null)
    try {
      const res = await fetch('/api/stock?symbol=SPY')
      if (res.status === 401) {
        setAuthed(false)
        return
      }
      if (!res.ok) throw new Error(`API returned ${res.status}`)
      const json = await res.json()
      setPrices(json.prices)
      setAuthed(true)
    } catch (err) {
      setAuthed(true) // we are logged in; this is a data error, not auth
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    loadStock()
  }, [loadStock])

  async function handleLogout() {
    await fetch('/api/login', { method: 'DELETE' })
    setPrices([])
    setAuthed(false)
  }

  if (authed === null) return <div className="status">Loading…</div>
  if (authed === false) return <Login onLogin={loadStock} />

  const latest = prices.length ? prices[prices.length - 1].close : null

  return (
    <>
      <header>
        <h1>SPY</h1>
        {latest != null && <span className="price">${latest.toFixed(2)}</span>}
        <button className="logout" onClick={handleLogout}>
          Log out
        </button>
      </header>

      {error && <div className="status error">Failed to load: {error}</div>}
      {prices.length > 0 && <Chart prices={prices} />}
    </>
  )
}
