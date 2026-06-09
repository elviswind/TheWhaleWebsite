import { useEffect, useRef } from 'react'
import { createChart } from 'lightweight-charts'

// One color per series (cycles if there are more series than colors).
const COLORS = [
  '#4caf50', '#1f6feb', '#ef5350', '#ffb300',
  '#ab47bc', '#26c6da', '#ec407a', '#8d6e63',
  '#9ccc65', '#5c6bc0',
]

// How each value is rendered, both on the axis and in the labels above.
const FORMATS = {
  price: { fn: (v) => `$${v.toFixed(2)}`, minMove: 0.01 },
  percent: { fn: (v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`, minMove: 0.01 },
  rsi: { fn: (v) => v.toFixed(1), minMove: 0.1 },
  number: { fn: (v) => v.toFixed(2), minMove: 0.01 },
}

const colorFor = (i) => COLORS[i % COLORS.length]

// Generic line chart. `series` is { label: [{ time, value }] } — one line per
// key, single- or multi-series. The latest value of each series is shown as a
// label above the chart so the current reading is unmistakable.
export default function Graph({ series, format = 'number' }) {
  const containerRef = useRef(null)
  const names = Object.keys(series)
  const { fn, minMove } = FORMATS[format] ?? FORMATS.number

  useEffect(() => {
    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#131722' }, textColor: '#d1d4dc' },
      grid: { vertLines: { color: '#2a2e39' }, horzLines: { color: '#2a2e39' } },
      autoSize: true,
      timeScale: { timeVisible: false, borderColor: '#2a2e39' },
      rightPriceScale: {
        borderColor: '#2a2e39',
        scaleMargins: { top: 0.15, bottom: 0.1 },
      },
    })

    names.forEach((name, i) => {
      const line = chart.addLineSeries({
        color: colorFor(i),
        lineWidth: 2,
        title: name,
        priceFormat: { type: 'custom', formatter: fn, minMove },
      })
      line.setData(series[name])
    })

    chart.timeScale().fitContent()
    return () => chart.remove()
    // `names` is derived from `series`, so `series` already covers it.
  }, [series, fn, minMove])

  return (
    <div className="graph">
      <div className="labels">
        {names.map((name, i) => {
          const points = series[name]
          const last = points.length ? points[points.length - 1] : null
          return (
            <div className="label" key={name}>
              <span className="label-name" style={{ color: colorFor(i) }}>
                ● {name}
              </span>
              <span className="label-value" style={{ color: colorFor(i) }}>
                {last ? fn(last.value) : '—'}
              </span>
            </div>
          )
        })}
      </div>
      <div ref={containerRef} className="chart" />
    </div>
  )
}
