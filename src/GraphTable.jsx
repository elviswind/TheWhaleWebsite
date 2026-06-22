import { FORMATS } from './Graph.jsx'

// Tabular view of a chart's data. `series` is { label: [{ time, value }] } —
// the same shape Graph consumes. We render one column per series and one row
// per session date (union of every series' times, newest first).
export default function GraphTable({ series, format = 'number' }) {
  const names = Object.keys(series)
  const { fn } = FORMATS[format] ?? FORMATS.number

  // Build time -> { label: value } and the sorted set of all dates.
  const byTime = {}
  for (const name of names) {
    for (const { time, value } of series[name]) {
      ;(byTime[time] ??= {})[name] = value
    }
  }
  const times = Object.keys(byTime).sort().reverse()

  return (
    <table className="quotes">
      <thead>
        <tr>
          <th></th>
          {names.map((name) => (
            <th key={name} className="sym">{name}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {times.map((time) => (
          <tr key={time}>
            <th>{time}</th>
            {names.map((name) => {
              const v = byTime[time][name]
              return <td key={name}>{v != null ? fn(v) : '—'}</td>
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
