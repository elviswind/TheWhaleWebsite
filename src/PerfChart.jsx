import { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'

// Distinct colors, one per ticker (cycles if there are more series than colors).
const COLORS = [
  '#4caf50', '#1f6feb', '#ef5350', '#ffb300',
  '#ab47bc', '#26c6da', '#ec407a', '#8d6e63',
  '#9ccc65', '#5c6bc0',
]

// `series` is { ticker: [{ time, value }] } where value is a cumulative
// return in percent. One line per ticker, all starting at 0.
export default function PerfChart({ series }) {
  const containerRef = useRef(null)
  const tickers = Object.keys(series)

  useEffect(() => {
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#131722' }, textColor: '#d1d4dc' },
      grid: { vertLines: { color: '#2a2e39' }, horzLines: { color: '#2a2e39' } },
      autoSize: true,
      timeScale: { timeVisible: false, borderColor: '#2a2e39' },
      rightPriceScale: {
        borderColor: '#2a2e39',
        // Cumulative return can go negative; show a zero baseline reference.
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
    })

    tickers.forEach((ticker, i) => {
      const line = chart.addLineSeries({
        color: COLORS[i % COLORS.length],
        lineWidth: 2,
        title: ticker,
        priceFormat: { type: 'custom', formatter: (v) => `${v.toFixed(2)}%` },
      })
      line.setData(series[ticker])
    })

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [series])

  return (
    <div className="perf">
      <div className="legend">
        {tickers.map((ticker, i) => (
          <span key={ticker} style={{ color: COLORS[i % COLORS.length] }}>
            ● {ticker}
          </span>
        ))}
      </div>
      <div ref={containerRef} className="chart" />
    </div>
  )
}
