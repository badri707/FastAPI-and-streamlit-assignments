import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmtDate, fmtTime, qs } from '../api'
import { Empty, Loaded, Notice, Pager, Pill, Stat, Tabs } from '../ui'
import { useAction, useLoad } from '../hooks'

export function Members() {
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [tier, setTier] = useState('')
  const [status, setStatus] = useState('active')
  const [segment, setSegment] = useState('')
  const [sort, setSort] = useState('name')
  const [page, setPage] = useState(1)
  const segs = useLoad(() => api.get('/api/segments'), [])
  const s = useLoad(() => api.get(`/api/members${qs({ q: term, tier, status, segment_id: segment, sort, desc: sort !== 'name', page })}`),
    [term, tier, status, segment, sort, page])
  const search = (e: FormEvent) => { e.preventDefault(); setPage(1); setTerm(q) }
  return (
    <>
      <h1>Members</h1>
      <div className="subtle" style={{ marginBottom: 10 }}>Identity is the source ID — several members can share a display name.</div>
      <div className="card">
        <h2>Saved segments</h2>
        <Loaded s={segs}>{rows => (
          <div className="row">
            {rows.map((sg: any) => (
              <button key={sg.id} className={String(sg.id) === segment ? 'primary' : ''} title={sg.description}
                onClick={() => { setPage(1); setSegment(String(sg.id) === segment ? '' : String(sg.id)) }}>
                {sg.name} <strong>{sg.count}</strong>
              </button>
            ))}
          </div>
        )}</Loaded>
      </div>
      <form className="row" onSubmit={search} style={{ marginBottom: 10 }}>
        <div><label htmlFor="mq">Search name, ID or email</label><input id="mq" value={q} onChange={e => setQ(e.target.value)} /></div>
        <div><label htmlFor="mt">Tier</label><select id="mt" value={tier} onChange={e => { setPage(1); setTier(e.target.value) }}><option value="">All</option><option>general</option><option>annual</option></select></div>
        <div><label htmlFor="ms">Status</label><select id="ms" value={status} onChange={e => { setPage(1); setStatus(e.target.value) }}><option value="">All</option><option>active</option><option>left</option><option>removed</option></select></div>
        <div><label htmlFor="so">Sort</label><select id="so" value={sort} onChange={e => setSort(e.target.value)}><option value="name">Name</option><option value="joined">Newest joined</option><option value="last_contribution">Most recent contribution</option></select></div>
        <button type="submit">Search</button>
      </form>
      <Loaded s={s}>{d => (
        <div className="card">
          {d.segment && <Notice>Segment <strong>{d.segment.name}</strong>: {d.segment.description} (params {JSON.stringify(d.segment.params)})</Notice>}
          {d.rows.length === 0 ? <Empty>No members match these filters.</Empty> : (
            <div className="table-wrap"><table>
              <thead><tr><th>Name</th><th>Role</th><th>Tier</th><th>Status</th><th>Joined</th><th>Last observed contribution</th><th>Tags</th><th>Data freshness</th></tr></thead>
              <tbody>
                {d.rows.map((m: any) => (
                  <tr key={m.id}>
                    <td><Link to={`/members/${m.id}`}>{m.display_name}</Link><div className="mono subtle">{m.upstream_id}</div></td>
                    <td>{m.role}</td><td>{m.tier ?? 'unknown'}</td><td><Pill v={m.status} kind={m.status === 'active' ? 'ok' : 'warn'} /></td>
                    <td>{fmtDate(m.joined_at)}</td><td>{m.last_observed_contribution ? fmtDate(m.last_observed_contribution) : <span className="subtle">none observed</span>}</td>
                    <td>{m.tags.map((t: string) => <Pill key={t} v={t} />)}</td><td className="subtle">{fmtTime(m.data_freshness)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
          <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          <div className="subtle" style={{ marginTop: 6 }}>{d.note}</div>
        </div>
      )}</Loaded>
    </>
  )
}

export function MemberDetail() {
  const { id } = useParams()
  const [tab, setTab] = useState('activity')
  const s = useLoad(() => api.get(`/api/members/${id}`), [id])
  const [note, setNote] = useState('')
  const [tag, setTag] = useState('')
  const act = useAction()
  return (
    <Loaded s={s}>{d => {
      const m = d.member, p = d.profile
      return (
        <>
          <Link to="/members">‹ Members</Link>
          <h1>{m.display_name} <Pill v={m.status} kind={m.status === 'active' ? 'ok' : 'warn'} /></h1>
          <div className="subtle">ID <span className="mono">{m.upstream_id}</span> · {m.role} · tier {m.tier ?? 'unknown'} · joined {fmtDate(m.joined_at)}
            {m.rejoin_count > 0 && ` · rejoined ${m.rejoin_count}×`} · onboarding {m.onboarding_status} · dataset {m.dataset}</div>
          {d.identity_note && <Notice>{d.identity_note}</Notice>}
          <div className="grid cols-4" style={{ margin: '12px 0' }}>
            <Stat label="Posts / comments" value={`${p.posts} / ${p.comments}`} hint={`last ${d.scope.start_ist} → ${d.scope.end_ist}`} />
            <Stat label="Reactions given / received" value={`${p.reactions_given} / ${p.reactions_received}`} />
            <Stat label="Active contribution days" value={p.active_contribution_days} hint="days with a post/comment/reaction" />
            <Stat label="Lessons marked complete" value={`${p.lessons_marked_complete} / ${p.accessible_lessons}`} hint="not proof of viewing" />
            <Stat label="Events attended" value={p.events_attended} hint={`${d.events_registered} registrations`} />
            <Stat label="Time spent" value={p.time_spent.minutes != null ? `${p.time_spent.minutes} min` : 'unknown'} hint={p.time_spent.note} />
          </div>
          {d.next_lesson && <Notice kind="ok">Suggested next lesson (within tier): <strong>{d.next_lesson.lesson}</strong> — {d.next_lesson.course}</Notice>}
          <Tabs value={tab} onChange={setTab} tabs={[['activity', 'Activity'], ['progress', 'Progress'], ['support', `Support (${d.support_items.length})`],
            ['followups', `Follow-ups (${d.follow_ups.length})`], ['notes', `Notes & tags`], ['data', 'Data']]} />
          {tab === 'activity' && <div className="card">
            {d.activity.length === 0 ? <Empty>No observed activity. That does not mean no visits or learning.</Empty> :
              <table><tbody>
                {d.activity.map((a: any, i: number) => (
                  <tr key={i}><td style={{ whiteSpace: 'nowrap' }}>{fmtTime(a.at)}</td><td><Pill v={a.type.replace('_', ' ')} kind="info" /></td>
                    <td><Link to={a.link}>{a.title || a.excerpt}</Link>{a.deleted && <Pill v="deleted" />}{a.edited && <Pill v="edited" />}</td>
                    <td className="subtle">{a.source}</td></tr>
                ))}
              </tbody></table>}
          </div>}
          {tab === 'progress' && <div className="card">
            {d.progress.map((c: any) => (
              <div key={c.course_id} style={{ marginBottom: 10 }}>
                <strong>{c.title}</strong> {!c.accessible && <Pill v="not in tier" kind="warn" />} <span className="subtle">{c.marked_complete}/{c.lessons} marked complete · access: {c.access_tiers} (synthetic)</span>
                <div className="row" style={{ marginTop: 4 }}>
                  {c.lesson_states.map((l: any) => <span key={l.title} title={l.at ? fmtTime(l.at) : 'not completed'} className={`pill ${l.completed ? 'ok' : ''}`}>{l.title}</span>)}
                </div>
              </div>
            ))}
            <h3>Assignments</h3>
            {d.submissions.length === 0 ? <Empty>No submissions.</Empty> : <table><thead><tr><th>Status</th><th>Submitted</th><th>Reviewed</th><th>Feedback</th></tr></thead><tbody>
              {d.submissions.map((x: any, i: number) => <tr key={i}><td><Pill v={x.status} /></td><td>{fmtDate(x.submitted_at)}</td><td>{fmtDate(x.reviewed_at)}</td><td>{x.feedback ?? '—'}</td></tr>)}
            </tbody></table>}
          </div>}
          {tab === 'support' && <div className="card">{d.support_items.length === 0 ? <Empty>No support items.</Empty> : <table><tbody>
            {d.support_items.map((x: any) => <tr key={x.id}><td><Link to={x.link}>{x.title}</Link></td><td><Pill v={x.status} /></td><td>{x.label} <span className="subtle">({x.label_source})</span></td><td>{fmtDate(x.created_at)}</td></tr>)}
          </tbody></table>}</div>}
          {tab === 'followups' && <div className="card">{d.follow_ups.length === 0 ? <Empty>No follow-up actions.</Empty> : <table><tbody>
            {d.follow_ups.map((x: any) => <tr key={x.id}><td><Link to={`/review/${x.id}`}>#{x.id} {x.kind}</Link></td><td><Pill v={x.state} /></td><td>{x.origin}</td><td>{x.simulated ? 'simulated' : ''}</td><td>{fmtTime(x.created_at)}</td></tr>)}
          </tbody></table>}</div>}
          {tab === 'notes' && <div className="card">
            {act.view}
            <form onSubmit={e => { e.preventDefault(); act.run(async () => { await api.post(`/api/members/${id}/notes`, { body: note }); setNote(''); s.reload() }) }}>
              <label htmlFor="note">Internal note (not visible to the member)</label>
              <textarea id="note" value={note} onChange={e => setNote(e.target.value)} required maxLength={4000} />
              <button className="primary" disabled={act.busy}>Add note</button>
            </form>
            {d.notes.map((n: any) => <div key={n.id} className="card" style={{ marginTop: 8 }}><div className="subtle">{n.author} · {fmtTime(n.created_at)}
              <button style={{ marginLeft: 8 }} onClick={() => act.run(async () => { await api.del(`/api/members/${id}/notes/${n.id}`); s.reload() })}>Delete</button></div><div style={{ whiteSpace: 'pre-wrap' }}>{n.body}</div></div>)}
            <h3 style={{ marginTop: 12 }}>Tags</h3>
            <div className="row">{m.tags.map((t: string) => <span key={t} className="pill">{t}{!t.startsWith('source:') && !t.startsWith('local:') &&
              <button aria-label={`Remove tag ${t}`} style={{ padding: '0 4px', marginLeft: 4, border: 'none', background: 'none' }} onClick={() => act.run(async () => { await api.del(`/api/members/${id}/tags/${encodeURIComponent(t)}`); s.reload() })}>×</button>}</span>)}</div>
            <form className="row" style={{ marginTop: 8 }} onSubmit={e => { e.preventDefault(); act.run(async () => { await api.post(`/api/members/${id}/tags`, { tag }); setTag(''); s.reload() }) }}>
              <div><label htmlFor="tag">Add tag</label><input id="tag" value={tag} onChange={e => setTag(e.target.value)} pattern="[A-Za-z0-9 _-]+" required /></div><button>Add</button>
            </form>
          </div>}
          {tab === 'data' && <div className="card">
            {act.view}
            <p>Export everything this application stores about this member, or erase their personal data locally.</p>
            <div className="row">
              <a className="btn" href={`/api/members/${id}/export`}>Export JSON</a>
              <button className="danger" onClick={() => { if (confirm('Erase this member\'s personal data in this app? This cannot be undone. The source community is not changed.')) act.run(async () => { await api.post(`/api/members/${id}/erase`); s.reload() }, 'Erased locally.') }}>Erase personal data locally</button>
              <button className="danger" onClick={() => { const reason = prompt('Reason for proposing removal (creates a DRAFT needing approval):'); if (reason) act.run(() => api.post('/api/actions/moderation', { member_id: Number(id), kind: 'remove_member', reason }), 'Draft created in the review queue — it still needs explicit approval.') }}>Propose removal…</button>
            </div>
          </div>}
        </>
      )
    }}</Loaded>
  )
}
