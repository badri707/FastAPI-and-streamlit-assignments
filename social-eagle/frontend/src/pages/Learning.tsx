import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmtTime, qs } from '../api'
import { Bars, Coverage, Empty, Loaded, Notice, Pill } from '../ui'
import { useLoad } from '../hooks'

export function Learning() {
  const s = useLoad(() => api.get('/api/learning/courses?days=30'), [])
  const [days, setDays] = useState(14)
  const st = useLoad(() => api.get(`/api/learning/stalled${qs({ days, limit: 50 })}`), [days])
  return (
    <>
      <h1>Learning</h1>
      <Loaded s={s}>{d => (
        <>
          <Notice>{d.provenance} {d.note}</Notice>
          <div className="card"><div className="table-wrap"><table>
            <thead><tr><th>Course</th><th>Access (synthetic)</th><th>Lessons</th><th>Eligible active</th><th>Started</th><th>All lessons marked complete</th><th>Rate</th></tr></thead>
            <tbody>{d.courses.map((c: any) => <tr key={c.course_id}><td><Link to={`/learning/${c.course_id}`}>{c.title}</Link></td><td>{c.access_tiers}</td><td>{c.lessons}</td>
              <td>{c.eligible_active_members}</td><td>{c.started}</td><td>{c.finished_all_marked_complete}</td><td>{c.finish_rate_of_eligible != null ? `${(c.finish_rate_of_eligible * 100).toFixed(1)}%` : '—'}</td></tr>)}</tbody>
          </table></div>
            <div className="subtle" style={{ marginTop: 6 }}>Progress events in last 30 days: {Object.entries(d.progress_events_in_range).map(([k, v]: any) => `${k}: ${v.events} by ${v.members} members`).join(' · ') || 'none'}</div>
            <Coverage c={d.coverage} />
          </div>
        </>
      )}</Loaded>
      <div className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Stalled progress</h2><div className="spacer" />
          <div><label htmlFor="sd">No progress for</label><select id="sd" value={days} onChange={e => setDays(Number(e.target.value))}>{[7, 14, 21, 30, 60].map(x => <option key={x} value={x}>{x} days</option>)}</select></div></div>
        <Loaded s={st}>{d => (
          <>
            <div className="subtle">{d.rule} — {d.total} members (showing up to 50).</div>
            {d.rows.length === 0 ? <Empty>None.</Empty> : <table><thead><tr><th>Member</th><th>Tier</th><th>Last progress</th><th>Suggested next lesson (in tier)</th></tr></thead><tbody>
              {d.rows.map((r: any) => <tr key={r.member_id}><td><Link to={`/members/${r.member_id}`}>{r.name}</Link></td><td>{r.tier}</td><td>{fmtTime(r.last_progress)}</td>
                <td>{r.next_lesson ? `${r.next_lesson.lesson} — ${r.next_lesson.course}` : '—'}</td></tr>)}</tbody></table>}
          </>
        )}</Loaded>
      </div>
    </>
  )
}

export function CourseDetail() {
  const { id } = useParams()
  const s = useLoad(() => api.get(`/api/learning/courses/${id}`), [id])
  return (
    <Loaded s={s}>{d => (
      <>
        <Link to="/learning">‹ Learning</Link>
        <h1>{d.course.title}</h1>
        <div className="subtle">Access: {d.course.access_tiers} · {d.course.policy_label}</div>
        <Notice>{d.note}</Notice>
        <div className="grid cols-2">
          <div className="card"><h2>Lessons — members marked complete</h2>
            <Bars rows={d.lessons.map((l: any) => ({ label: `${l.position}. ${l.title}`, value: l.members_marked_complete }))} /></div>
          <div className="card"><h2>Assignments</h2>
            {d.assignments.length === 0 ? <Empty>No assignments.</Empty> : d.assignments.map((a: any) => (
              <div key={a.id} style={{ marginBottom: 8 }}><strong>{a.title}</strong><div className="subtle">{Object.entries(a.submissions).map(([k, v]) => `${k}: ${v}`).join(' · ') || 'no submissions'} · awaiting review {a.awaiting_review}</div></div>))}
            <h3>Recent progress (14 days)</h3>
            {d.recent_progress.length === 0 ? <Empty>No recent progress.</Empty> : <table><tbody>{d.recent_progress.map((p: any, i: number) => (
              <tr key={i}><td><Link to={`/members/${p.member_id}`}>{p.member}</Link></td><td>{p.lesson}</td><td><Pill v={p.kind} kind={p.kind === 'completed' ? 'ok' : 'warn'} /></td><td>{fmtTime(p.at)}</td></tr>))}</tbody></table>}
          </div>
        </div>
      </>
    )}</Loaded>
  )
}

export function Events() {
  const s = useLoad(() => api.get('/api/events?past_days=60&future_days=30'), [])
  return (
    <>
      <h1>Events</h1>
      <Loaded s={s}>{d => (
        <div className="card">
          <Notice>{d.note}</Notice>
          <div className="table-wrap"><table><thead><tr><th>Event</th><th>Starts</th><th>Registered</th><th>Attended (registered / walk-in)</th><th>Rate</th><th>Duration known / unknown</th><th>Avg known min</th></tr></thead>
            <tbody>{[...d.events].reverse().map((e: any) => <tr key={e.event_id}><td><Link to={`/events/${e.event_id}`}>{e.title}</Link> {e.upcoming && <Pill v="upcoming" kind="info" />}</td>
              <td>{fmtTime(e.starts_at)}</td><td>{e.registered}</td><td>{e.upcoming ? '—' : `${e.attended} (${e.attended_registered} / ${e.walk_ins})`}</td>
              <td>{e.attendance_rate_of_registered != null && !e.upcoming ? `${Math.round(e.attendance_rate_of_registered * 100)}%` : '—'}</td>
              <td>{e.upcoming ? '—' : `${e.duration_known} / ${e.duration_unknown}`}</td><td>{e.avg_known_duration_min ?? '—'}</td></tr>)}</tbody></table></div>
        </div>
      )}</Loaded>
    </>
  )
}

export function EventDetail() {
  const { id } = useParams()
  const s = useLoad(() => api.get(`/api/events/${id}`), [id])
  return (
    <Loaded s={s}>{d => (
      <>
        <Link to="/events">‹ Events</Link>
        <h1>{d.event.title}</h1>
        <div className="subtle">{fmtTime(d.event.starts_at)} → {fmtTime(d.event.ends_at)} {d.event.upcoming && <Pill v="upcoming" kind="info" />}</div>
        <div className="card"><table><thead><tr><th>Member</th><th>Registered</th><th>Attended</th><th>Duration</th></tr></thead><tbody>
          {d.people.map((p: any) => <tr key={p.member_id}><td><Link to={`/members/${p.member_id}`}>{p.name}</Link></td><td>{p.registered ? fmtTime(p.registered_at) : 'no (walk-in)'}</td>
            <td>{p.attended ? 'yes' : 'no'}</td><td>{p.duration_status === 'known' ? `${p.duration_minutes} min` : p.duration_status}</td></tr>)}</tbody></table></div>
      </>
    )}</Loaded>
  )
}
