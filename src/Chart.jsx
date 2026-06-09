import { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'

export default function Chart({ prices }) {
  const containerRef = useRef(null)

  useEffect(() => {
    const chart = createChart(containerRef.current, {
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

    const lineSeries = chart.addLineSeries({ color: '#4caf50', lineWidth: 2 })
    lineSeries.setData(prices) // already [{ time, value }] from /api/stock
    chart.timeScale().fitContent()

    return () => chart.remove()
  }, [prices])

  return <div ref={containerRef} className="chart" />
}
