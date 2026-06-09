import { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'

export default function App() {
  const chartContainerRef = useRef(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)
  const [latest, setLatest] = useState(null)

  useEffect(() => {
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#131722' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#2a2e39' },
        horzLines: { color: '#2a2e39' },
      },
      autoSize: true,
      timeScale: { timeVisible: false, borderColor: '#2a2e39' },
      rightPriceScale: { borderColor: '#2a2e39' },
    })

    const lineSeries = chart.addLineSeries({
      color: '#4caf50',
      lineWidth: 2,
    })

    let cancelled = false

    async function load() {
      try {
        const res = await fetch('/api/stock?symbol=SPY')
        if (!res.ok) throw new Error(`API returned ${res.status}`)
        const json = await res.json()
        if (cancelled) return

        const points = json.prices.map((p) => ({ time: p.date, value: p.close }))
        lineSeries.setData(points)
        chart.timeScale().fitContent()

        const last = points[points.length - 1]
        if (last) setLatest(last.value)
        setStatus('ready')
      } catch (err) {
        if (cancelled) return
        setError(err.message)
        setStatus('error')
      }
    }

    load()

    return () => {
      cancelled = true
      chart.remove()
    }
  }, [])

  return (
    <>
      <header>
        <h1>SPY</h1>
        {latest != null && <span className="price">${latest.toFixed(2)}</span>}
      </header>

      {status === 'loading' && <div className="status">Loading price history…</div>}
      {status === 'error' && <div className="status error">Failed to load: {error}</div>}

      <div ref={chartContainerRef} className="chart" />
    </>
  )
}
