import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs } from '../api'
import { Coverage, LineChart, Loaded, Pill, Stat } from '../ui'
import { useLoad } from '../hooks'

export function Engagement() {
  const [days, setDays] = useState(30)
  const s = useLoad(() => api.get(`/api/engagement${qs({ days })}`), [days])
  return (
    <>
      <div className="row"><h1>Engagement</h1><div className="spacer" />
        <select aria-label="Period" value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 14, 30, 60, 90].map(d => <option key={d} value={d}>Last {d} days</option>)}</select></div>
      <Loaded s={s}>{d => {
        const c = d.contributions, labels = Object.keys(c.daily)
        return (
          <>
            <div className="grid cols-4" style={{ margin: '10px 0' }}>
              {d.comparison.rows.map((r: any) => <Stat key={r.metric} label={r.metric.replaceAll('_', ' ')} value={r.b} hint={`previous period ${r.a}${r.pct_change != null ? ` (${r.pct_change > 0 ? '+' : ''}${r.pct_change}%)` : ''}`} />)}
            </div>
            <div className="card"><LineChart incompleteLast={d.coverage?.notes?.some((n: string) => n.includes('incomplete'))} labels={labels} series={[{ name: 'Reactions', values: labels.map(k => c.daily[k].reactions), color: '#c9a227' },
              { name: 'Comments', values: labels.map(k => c.daily[k].comments), color: '#a4161a' }, { name: 'Posts', values: labels.map(k => c.daily[k].posts), color: '#2a2a2c' }]} /></div>
            <div className="card">
              <h2>Leaderboard (snapshot {d.leaderboard.latest?.slice(0, 10)})</h2>
              <div className="subtle" style={{ marginBottom: 6 }}>{d.leaderboard.note}</div>
              <table><thead><tr><th>#</th><th>Member</th><th>Points</th><th>Level</th><th>Change vs previous</th></tr></thead><tbody>
                {d.leaderboard.rows.map((r: any, i: number) => <tr key={r.member_id}><td>{i + 1}</td><td><Link to={`/members/${r.member_id}`}>{r.name}</Link></td><td>{r.points}</td><td>{r.level}</td><td>{r.change == null ? 'new' : r.change > 0 ? `+${r.change}` : r.change}</td></tr>)}
              </tbody></table>
            </div>
            <div className="card"><h2>Definitions</h2><ul>{Object.entries(d.definitions).map(([k, v]) => <li key={k}><strong>{k}</strong> = {String(v)}</li>)}</ul></div>
            <Coverage c={d.coverage} />
          </>
        )
      }}</Loaded>
    </>
  )
}

export function Reports() {
  const [period, setPeriod] = useState('daily')
  const s = useLoad(() => api.get(`/api/reports/summary${qs({ period })}`), [period])
  const sup = useLoad(() => api.get('/api/reports/support?days=30'), [])
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const range = qs({ start, end, days: start ? undefined : 30 })
  return (
    <>
      <h1>Reports</h1>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Summary</h2><div className="spacer" />
          <select aria-label="Summary period" value={period} onChange={e => setPeriod(e.target.value)}><option value="daily">Yesterday</option><option value="weekly">Last 7 days vs previous 7</option></select></div>
        <Loaded s={s}>{d => period === 'daily' ? <pre className="box">{d.text}</pre> : (
          <>
            <table><thead><tr><th>Metric</th><th>Previous week</th><th>This week</th><th>Change</th></tr></thead><tbody>
              {d.comparison.rows.map((r: any) => <tr key={r.metric}><td>{r.metric}</td><td>{r.a}</td><td>{r.b}</td><td>{r.delta} {r.pct_change != null && `(${r.pct_change}%)`}</td></tr>)}</tbody></table>
            <Coverage c={d.coverage} />
          </>
        )}</Loaded>
      </div>
      <div className="card">
        <h2>Response and resolution times (last 30 days)</h2>
        <Loaded s={sup}>{d => (
          <>
            <div className="grid cols-4">
              <Stat label="Questions asked" value={d.questions_in_range} />
              <Stat label="Got a first response" value={d.answered_in_range} />
              <Stat label="Median first response" value={d.first_response.median_hours != null ? `${d.first_response.median_hours} h` : 'n/a'} hint={`p90 ${d.first_response.p90_hours ?? 'n/a'} h`} />
              <Stat label="Human-verified resolution (median)" value={d.human_verified_resolution.median_hours != null ? `${d.human_verified_resolution.median_hours} h` : 'n/a'} hint={`${d.human_verified_resolution.n} resolved by staff`} />
            </div>
            <div className="subtle" style={{ marginTop: 6 }}>By responder: {Object.entries(d.first_response_by).map(([k, v]: any) => `${k} ${v.n} (median ${v.median_hours} h)`).join(' · ')}</div>
            <div className="subtle">Definitions: {d.definitions.unanswered} · {d.definitions.first_response}</div>
          </>
        )}</Loaded>
      </div>
      <div className="card">
        <h2>CSV exports</h2>
        <div className="row" style={{ marginBottom: 8 }}>
          <div><label htmlFor="rs">From (IST)</label><input id="rs" type="date" value={start} onChange={e => setStart(e.target.value)} /></div>
          <div><label htmlFor="re">To (IST)</label><input id="re" type="date" value={end} onChange={e => setEnd(e.target.value)} /></div>
          <span className="subtle">Blank = last 30 days</span>
        </div>
        <div className="row">{['members', 'daily', 'support', 'actions', 'progress'].map(k => <a key={k} className="btn" href={`/api/reports/export/${k}${range}`}>{k}.csv</a>)}</div>
        <div className="subtle" style={{ marginTop: 6 }}>Each CSV starts with scope, date range, source, last sync and missing-data notes, and is labelled <Pill v="SYNTHETIC" kind="warn" /> with simulated delivery. Cells are protected against spreadsheet formula injection.</div>
      </div>
    </>
  )
}
