import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmtTime, qs } from '../api'
import { Empty, Loaded, Notice, Pager, Pill, Tabs } from '../ui'
import { useAction, useLoad } from '../hooks'

export function ReviewQueue() {
  const [tab, setTab] = useState('review')
  const [page, setPage] = useState(1)
  const states: Record<string, string> = { review: 'drafted,held,unknown_outcome', pending: 'approved,queued,sending', done: 'sent,verified', closed: 'rejected,cancelled,failed', all: '' }
  const s = useLoad(() => api.get(`/api/actions${qs({ state: states[tab], page })}`), [tab, page])
  return (
    <>
      <h1>Review queue & action history</h1>
      <div className="subtle">Every outward action shows whether it is drafted, approved, sent or verified. In evaluation mode delivery is always to the local simulator.</div>
      <Tabs value={tab} onChange={v => { setTab(v); setPage(1) }} tabs={[['review', 'Needs review'], ['pending', 'Approved / sending'], ['done', 'Sent / verified'], ['closed', 'Rejected / cancelled / failed'], ['all', 'All']]} />
      <Loaded s={s}>{d => (
        <div className="card">
          <div className="subtle" style={{ marginBottom: 6 }}>Counts: {Object.entries(d.counts).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none'}</div>
          {d.rows.length === 0 ? <Empty>Nothing in this view.</Empty> : <div className="table-wrap"><table>
            <thead><tr><th>Action</th><th>Stage</th><th>Answer check</th><th>Target</th><th>Origin</th><th>Delivery</th><th>Updated</th></tr></thead>
            <tbody>{d.rows.map((a: any) => <tr key={a.id}><td><Link to={`/review/${a.id}`}>#{a.id} {a.kind}</Link>{a.consequential && <> <Pill v="consequential" kind="bad" /></>}</td>
              <td><Pill v={a.state} /> <span className="subtle">{a.stage}</span></td><td>{a.answer_status ? <Pill v={a.answer_status} /> : '—'}</td>
              <td className="mono">{a.member_name ?? a.target_upstream_id}</td><td>{a.origin}</td><td>{a.simulated ? 'simulated (local)' : a.delivery_target}</td><td>{fmtTime(a.updated_at)}</td></tr>)}</tbody>
          </table></div>}
          <Pager page={page} pageSize={50} total={d.total} onPage={setPage} />
        </div>
      )}</Loaded>
    </>
  )
}

export function ActionDetail() {
  const { id } = useParams()
  const s = useLoad(() => api.get(`/api/actions/${id}`), [id])
  const act = useAction()
  const [body, setBody] = useState<string | null>(null)
  return (
    <Loaded s={s}>{a => {
      const editable = ['drafted', 'held'].includes(a.state)
      const run = (fn: () => Promise<unknown>, ok: string) => act.run(async () => { await fn(); setBody(null); s.reload() }, ok)
      return (
        <>
          <Link to="/review">‹ Review queue</Link>
          <h1>Action #{a.id}: {a.kind} <Pill v={a.state} /></h1>
          <div className="subtle">{a.stage} · origin {a.origin} · {a.simulated ? 'SIMULATED delivery to the local simulator' : a.delivery_target} · payload v{a.payload_version}
            {a.approved_by && ` · approved by ${a.approved_by} ${fmtTime(a.approved_at)}`}{a.remote_id && ` · remote id ${a.remote_id}`}</div>
          {a.consequential && <Notice kind="warn">Consequential action: requires explicit human approval and is never automatic.</Notice>}
          {a.error && <Notice kind="error">{a.error}</Notice>}
          {a.auto_blocked_reason && <Notice kind="warn">Not auto-published: {a.auto_blocked_reason}</Notice>}
          {act.view}
          <div className="card">
            <div className="ai-label">{a.payload?.ai_label ?? 'Draft'} {a.answer_status && <Pill v={a.answer_status} />}</div>
            {editable ? <textarea aria-label="Draft text" style={{ minHeight: 180 }} value={body ?? a.body ?? ''} onChange={e => setBody(e.target.value)} />
              : <div style={{ whiteSpace: 'pre-wrap' }}>{a.body}</div>}
            {a.reasons?.length > 0 && <div className="subtle">Checks: {a.reasons.join('; ')}</div>}
            {editable && <div className="row" style={{ marginTop: 8 }}>
              {body !== null && body !== a.body && <button onClick={() => run(() => api.put(`/api/actions/${a.id}`, { body }), 'Draft saved (new version).')}>Save edit</button>}
              <button className="primary" onClick={() => run(async () => { if (body !== null && body !== a.body) await api.put(`/api/actions/${a.id}`, { body }); await api.post(`/api/actions/${a.id}/approve`) }, 'Approved and queued for delivery.')}>{body !== null && body !== a.body ? 'Save & approve' : 'Approve'}</button>
              <button className="danger" onClick={() => { const r = prompt('Reason for rejecting (optional)') ?? ''; run(() => api.post(`/api/actions/${a.id}/reject`, { reason: r }), 'Rejected.') }}>Reject</button>
            </div>}
          </div>
          {a.payload?.citations?.length > 0 && <div className="card"><h2>Evidence cited</h2>{a.payload.citations.map((c: any) => (
            <div key={c.id} className="facts-box" style={{ marginBottom: 6 }}><Link to={c.link}>[{c.id}] {c.title}</Link> <span className="subtle">v{c.version} · {c.updated}</span><div style={{ fontSize: '0.86rem' }}>{c.excerpt}</div></div>))}</div>}
          {a.ai_run && <div className="card"><h2>AI run</h2><div className="subtle">Run #{a.ai_run.id} · {a.ai_run.model} {a.ai_run.digest} · {a.ai_run.policy_version} · {a.ai_run.latency_ms} ms · <Pill v={a.ai_run.status} /></div>
            {a.ai_run.detail && <div className="subtle">{a.ai_run.detail}</div>}<div className="mono subtle">retrieved: {JSON.stringify(a.ai_run.retrieved)}</div></div>}
          <div className="card"><h2>Attempts</h2>{a.attempts.length === 0 ? <Empty>No delivery attempts yet.</Empty> : <table><tbody>{a.attempts.map((t: any) => (
            <tr key={t.no}><td>#{t.no}</td><td><Pill v={t.outcome} /></td><td>{t.detail}</td><td>{fmtTime(t.at)}</td></tr>))}</tbody></table>}</div>
        </>
      )
    }}</Loaded>
  )
}

export function Automation() {
  const s = useLoad(() => api.get('/api/automation/rules'), [])
  const act = useAction()
  const [edit, setEdit] = useState<any>(null)
  const save = () => act.run(async () => {
    const { id, consequential: _c, updated_at: _u, evaluation_only: _e, ...body } = edit
    void _c; void _u; void _e
    await (id ? api.put(`/api/automation/rules/${id}`, body) : api.post('/api/automation/rules', body)); setEdit(null); s.reload()
  }, 'Rule saved.')
  return (
    <>
      <h1>Automation rules</h1>
      <Loaded s={s}>{d => (
        <>
          <Notice>{d.policy} Quiet hours use Asia/Kolkata time. Limits count actions per rule. Outdated items expire instead of being sent late.</Notice>
          {act.view}
          <div className="card"><div className="table-wrap"><table>
            <thead><tr><th>Rule</th><th>Trigger → action</th><th>Mode</th><th>Enabled</th><th>Quiet hours</th><th>Limits</th><th>Expires after</th><th></th></tr></thead>
            <tbody>{d.rules.map((r: any) => <tr key={r.id}><td><strong>{r.name}</strong><div className="subtle">{r.description}</div></td><td>{r.trigger} → {r.action_kind}</td>
              <td><Pill v={r.mode} kind={r.mode === 'auto' ? 'bad' : 'info'} />{r.evaluation_only && <div className="subtle">evaluation only</div>}</td>
              <td><button onClick={() => act.run(async () => { const { id, consequential: _c, updated_at: _u, evaluation_only: _e, ...b } = r; void _c; void _u; void _e; await api.put(`/api/automation/rules/${id}`, { ...b, enabled: !r.enabled }); s.reload() })}>{r.enabled ? 'On' : 'Off'}</button></td>
              <td>{r.quiet_start ? `${r.quiet_start}–${r.quiet_end}` : 'none'}</td><td>{r.max_per_hour}/h · {r.max_per_day}/day</td><td>{r.expire_after_minutes} min</td>
              <td><button onClick={() => setEdit({ ...r })}>Edit</button></td></tr>)}</tbody>
          </table></div>
            <button style={{ marginTop: 8 }} onClick={() => setEdit({ name: '', trigger: 'new_question', action_kind: 'reply', mode: 'draft', enabled: false, conditions: { labels: ['question'] }, quiet_start: null, quiet_end: null, max_per_hour: 5, max_per_day: 30, expire_after_minutes: 240, description: '' })}>New rule</button>
          </div>
          {edit && <div className="card">
            <h2>{edit.id ? 'Edit rule' : 'New rule'}</h2>
            <div className="row">
              <div><label htmlFor="rn">Name</label><input id="rn" value={edit.name} onChange={e => setEdit({ ...edit, name: e.target.value })} /></div>
              <div><label htmlFor="rt">Trigger</label><select id="rt" value={edit.trigger} onChange={e => setEdit({ ...edit, trigger: e.target.value })}>{d.triggers.map((t: string) => <option key={t}>{t}</option>)}</select></div>
              <div><label htmlFor="ra">Action</label><select id="ra" value={edit.action_kind} onChange={e => setEdit({ ...edit, action_kind: e.target.value })}>{d.action_kinds.map((t: string) => <option key={t}>{t}</option>)}</select></div>
              <div><label htmlFor="rm">Mode</label><select id="rm" value={edit.mode} onChange={e => setEdit({ ...edit, mode: e.target.value })}><option value="draft">draft (needs approval)</option><option value="auto">auto (evaluation only)</option></select></div>
              <div><label htmlFor="qs">Quiet from</label><input id="qs" placeholder="23:00" value={edit.quiet_start ?? ''} onChange={e => setEdit({ ...edit, quiet_start: e.target.value || null })} /></div>
              <div><label htmlFor="qe">Quiet until</label><input id="qe" placeholder="07:00" value={edit.quiet_end ?? ''} onChange={e => setEdit({ ...edit, quiet_end: e.target.value || null })} /></div>
              <div><label htmlFor="mh">Max/hour</label><input id="mh" type="number" value={edit.max_per_hour} onChange={e => setEdit({ ...edit, max_per_hour: Number(e.target.value) })} style={{ width: 80 }} /></div>
              <div><label htmlFor="md">Max/day</label><input id="md" type="number" value={edit.max_per_day} onChange={e => setEdit({ ...edit, max_per_day: Number(e.target.value) })} style={{ width: 80 }} /></div>
              <div><label htmlFor="ex">Expire (min)</label><input id="ex" type="number" value={edit.expire_after_minutes} onChange={e => setEdit({ ...edit, expire_after_minutes: Number(e.target.value) })} style={{ width: 90 }} /></div>
            </div>
            <label htmlFor="rc" style={{ marginTop: 8 }}>Conditions (JSON)</label>
            <textarea id="rc" className="mono" value={JSON.stringify(edit.conditions)} onChange={e => { try { setEdit({ ...edit, conditions: JSON.parse(e.target.value) }) } catch { /* keep typing */ } }} />
            <label><input type="checkbox" checked={edit.enabled} onChange={e => setEdit({ ...edit, enabled: e.target.checked })} /> Enabled</label>
            <div className="row" style={{ marginTop: 8 }}><button className="primary" onClick={save}>Save</button><button onClick={() => setEdit(null)}>Cancel</button></div>
          </div>}
        </>
      )}</Loaded>
    </>
  )
}
