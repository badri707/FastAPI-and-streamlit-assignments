import { useState } from 'react'
import { api, fmtTime } from '../api'
import { Loaded, Notice, Pill, Tabs } from '../ui'
import { useAction, useLoad } from '../hooks'

export function System({ sys }: { sys: any }) {
  const [tab, setTab] = useState('status')
  const act = useAction()
  return (
    <>
      <h1>System & settings</h1>
      {act.view}
      <Tabs value={tab} onChange={setTab} tabs={[['status', 'Status'], ['jobs', 'Jobs'], ['settings', 'Settings'], ['notifications', 'Notifications'], ['diagnostics', 'Diagnostics']]} />
      {tab === 'status' && (sys ? <StatusTab sys={sys} act={act} /> : <Notice>Loading status…</Notice>)}
      {tab === 'jobs' && <JobsTab act={act} />}
      {tab === 'settings' && <SettingsTab act={act} />}
      {tab === 'notifications' && <NotificationsTab />}
      {tab === 'diagnostics' && <DiagnosticsTab />}
    </>
  )
}

function StatusTab({ sys, act }: { sys: any; act: ReturnType<typeof useAction> }) {
  return (
    <>
      <div className="card">
        <h2>Global pause</h2>
        <p>{sys.paused ? <><Pill v="PAUSED" kind="bad" /> New outbound actions will not start. {sys.paused_reason && `Reason: ${sys.paused_reason}`}</> : <><Pill v="running" kind="ok" /> Automation may send (simulated) actions according to rules.</>}</p>
        {sys.actions_in_progress.length > 0 && <Notice kind="warn">In progress: {sys.actions_in_progress.map((a: any) => `#${a.id} ${a.kind} (${a.state})`).join(', ')} — these are reconciled before any retry.</Notice>}
        <button className={sys.paused ? 'primary' : 'danger'} onClick={() => act.run(() => api.post('/api/system/pause', { paused: !sys.paused, reason: sys.paused ? null : 'paused from System page' }), sys.paused ? 'Resumed.' : 'Paused.')}>{sys.paused ? 'Resume automation' : 'Pause all automation'}</button>
      </div>
      <div className="grid cols-2">
        <div className="card"><h2>Worker & queue</h2>
          <p>Worker <Pill v={sys.worker.state} /> {sys.worker.pid && `pid ${sys.worker.pid}`} · last heartbeat {sys.worker.last_beat_age_s ?? '—'} s ago · {sys.worker.current_job ?? 'idle'}</p>
          <p className="subtle">Queue: {Object.entries(sys.queue).filter(([k]) => k !== 'oldest_queued_age_s').map(([k, v]) => `${k} ${v}`).join(' · ')}. Oldest pending {sys.queue.oldest_queued_age_s != null ? `${Math.round(sys.queue.oldest_queued_age_s)} s` : '—'}.</p>
          <Notice kind="warn">{sys.availability_note}</Notice></div>
        <div className="card"><h2>Connection & sync</h2>
          <p>Mode <strong>{sys.run_mode}</strong> · {sys.connection.simulated ? 'local simulator' : ''} <Pill v={sys.connection.status} /> · live Skool: {sys.live_connection}</p>
          {sys.sync.map((s: any) => <p key={s.source} className="subtle">Sync {s.source}: <Pill v={s.status} /> last success {fmtTime(s.last_success)} · freshness {s.freshness_s != null ? `${Math.round(s.freshness_s)} s` : '—'} · cursor {s.cursor}{s.last_error && <><br />{s.last_error}</>}</p>)}
        </div>
        <div className="card"><h2>Local AI</h2>
          <p><Pill v={sys.ai.status} /> {sys.ai.model} {sys.ai.ollama_version && `· Ollama ${sys.ai.ollama_version}`} · context {sys.ai.num_ctx} · breaker {sys.ai.breaker?.open ? 'OPEN' : 'closed'}</p>
          {sys.ai.retrieval && <p className="subtle">Retrieval: {sys.ai.retrieval} ({sys.ai.embed_model})</p>}
          <p className="subtle">{sys.ai.detail ?? 'Runs locally via Ollama; no cloud provider is configured. When unavailable, AI features show "unavailable" and the rest of the app keeps working.'}</p></div>
        <div className="card"><h2>Storage</h2>
          <p>{sys.disk.free_mb} MB free at <span className="mono">{sys.disk.data_dir}</span> {sys.disk.low && <Pill v="LOW" kind="bad" />}</p>
          <p className="subtle">External SSD: {sys.external_ssd.configured === false ? sys.external_ssd.note : `${sys.external_ssd.path} — ${sys.external_ssd.present ? 'present' : 'NOT PRESENT (optional; app keeps running)'}`}</p>
          <p className="subtle">Test clock: {sys.clock.local} ({sys.clock.mode})</p>
          <button onClick={() => act.run(() => api.post('/api/system/clock/advance', { advance_minutes: 60 }), 'Test clock advanced 1 hour.')}>Advance test clock +1 h</button>{' '}
          <button onClick={() => act.run(() => api.post('/api/system/clock/advance', { advance_minutes: 1440 }), 'Test clock advanced 1 day.')}>+1 day</button></div>
      </div>
    </>
  )
}

function JobsTab({ act }: { act: ReturnType<typeof useAction> }) {
  const [filter, setFilter] = useState('')
  const s = useLoad(() => api.get(`/api/jobs${filter ? `?status=${filter}` : ''}`), [filter])
  return (
    <div className="card">
      <div className="row"><select aria-label="Job status filter" value={filter} onChange={e => setFilter(e.target.value)}><option value="">All recent</option><option value="queued,leased">Queued/running</option><option value="failed,held">Failed/held</option><option value="expired,cancelled">Expired/cancelled</option></select><button onClick={s.reload}>Refresh</button></div>
      <Loaded s={s}>{d => <div className="table-wrap"><table><thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Run after</th><th>Error / result</th><th></th></tr></thead><tbody>
        {d.rows.map((j: any) => <tr key={j.id}><td>{j.id}</td><td>{j.kind}<div className="mono subtle">{j.dedupe_key}</div></td><td><Pill v={j.status} /></td><td>{j.attempts}/{j.max_attempts}</td><td>{fmtTime(j.run_after)}</td>
          <td className="subtle" style={{ maxWidth: 360 }}>{j.last_error ?? (j.result ? JSON.stringify(j.result).slice(0, 160) : '')}</td>
          <td>{['failed', 'held'].includes(j.status) && <button onClick={() => act.run(async () => { await api.post(`/api/jobs/${j.id}/retry`); s.reload() }, 'Requeued.')}>Retry</button>}
            {['queued', 'held', 'failed'].includes(j.status) && <button onClick={() => act.run(async () => { await api.post(`/api/jobs/${j.id}/cancel`); s.reload() }, 'Cancelled.')}>Cancel</button>}</td></tr>)}
      </tbody></table></div>}</Loaded>
    </div>
  )
}

function SettingsTab({ act }: { act: ReturnType<typeof useAction> }) {
  const s = useLoad(() => api.get('/api/system/settings'), [])
  const [pw, setPw] = useState({ current: '', new: '' })
  return (
    <Loaded s={s}>{d => (
      <>
        <div className="card"><h2>Thresholds</h2>
          <div className="row">{['new_member_days', 'quiet_days', 'stalled_progress_days', 'unanswered_hours'].map(k => (
            <div key={k}><label htmlFor={k}>{k.replaceAll('_', ' ')}</label><input id={k} type="number" min={1} max={365} defaultValue={d.thresholds[k]} style={{ width: 110 }}
              onBlur={e => act.run(async () => { await api.put('/api/system/settings', { thresholds: { [k]: Number(e.target.value) } }); s.reload() }, 'Saved.')} /></div>))}</div>
          <p className="subtle">Support keywords (rule v1): {d.thresholds.support_keywords.join(', ')}</p></div>
        <div className="card"><h2>AI task modes</h2>
          <div className="row">
            <div><label htmlFor="fr">FAQ replies</label><select id="fr" value={d.ai_task_modes.faq_reply} onChange={e => act.run(async () => { await api.put('/api/system/settings', { ai_task_modes: { ...d.ai_task_modes, faq_reply: e.target.value } }); s.reload() }, 'Saved.')}>
              <option value="draft">rules decide (auto only where allowed)</option><option value="draft_only">draft-only (force review)</option></select></div>
            <div><label htmlFor="oc">Owner chat</label><select id="oc" value={d.ai_task_modes.owner_chat} onChange={e => act.run(async () => { await api.put('/api/system/settings', { ai_task_modes: { ...d.ai_task_modes, owner_chat: e.target.value } }); s.reload() }, 'Saved.')}>
              <option value="enabled">enabled</option><option value="disabled">disabled</option></select></div>
          </div></div>
        <div className="card"><h2>Datasets used in statistics</h2>
          <p>Currently: {d.dataset_selection.map((x: string) => <Pill key={x} v={x} kind={x === 'synthetic' ? 'warn' : 'info'} />)}</p>
          <p className="subtle">Imported data is never mixed with synthetic statistics unless you select it explicitly (e.g. per report with ?datasets=import:3).</p></div>
        <div className="card"><h2>Retention (days)</h2>
          <div className="row">{Object.entries(d.retention_days).map(([k, v]) => <div key={k}><label htmlFor={`r-${k}`}>{k}</label><input id={`r-${k}`} type="number" min={1} defaultValue={v as number} style={{ width: 90 }}
            onBlur={e => act.run(async () => { await api.put('/api/system/settings', { retention_days: { ...d.retention_days, [k]: Number(e.target.value) } }); s.reload() }, 'Saved.')} /></div>)}
            <button onClick={() => act.run(async () => { const r = await api.post('/api/retention/run'); act.setMsg({ kind: 'ok', text: `Retention applied: ${JSON.stringify(r)}` }) })}>Apply retention now</button></div></div>
        <div className="card"><h2>Change password</h2>
          <form className="row" onSubmit={e => { e.preventDefault(); act.run(() => api.post('/api/auth/password', pw), 'Password changed; sign in again.') }}>
            <div><label htmlFor="pc">Current</label><input id="pc" type="password" autoComplete="current-password" value={pw.current} onChange={e => setPw({ ...pw, current: e.target.value })} /></div>
            <div><label htmlFor="pn">New (min 10)</label><input id="pn" type="password" autoComplete="new-password" value={pw.new} onChange={e => setPw({ ...pw, new: e.target.value })} /></div>
            <button>Change</button></form></div>
      </>
    )}</Loaded>
  )
}

function NotificationsTab() {
  const s = useLoad(() => api.get('/api/system/notifications'), [])
  return <Loaded s={s}>{rows => <div className="card"><table><tbody>{rows.map((n: any) => <tr key={n.id} style={{ opacity: n.read ? 0.6 : 1 }}>
    <td><Pill v={n.level} kind={n.level === 'error' ? 'bad' : n.level === 'warn' ? 'warn' : 'info'} /></td><td><strong>{n.title}</strong><div className="subtle" style={{ whiteSpace: 'pre-wrap' }}>{n.body}</div></td><td>{fmtTime(n.at)}</td>
    <td>{!n.read && <button onClick={() => api.post(`/api/system/notifications/${n.id}/read`).then(s.reload)}>Mark read</button>}</td></tr>)}</tbody></table></div>}</Loaded>
}

function DiagnosticsTab() {
  const s = useLoad(() => api.get('/api/system/diagnostics'), [])
  return <Loaded s={s}>{d => (
    <>
      <div className="card"><h2>Recent AI runs</h2><p className="subtle">Latency median {d.ai_latency_ms.median ?? '—'} ms, max {d.ai_latency_ms.max ?? '—'} ms over {d.ai_latency_ms.n} runs. Prompts are stored only as SHA-256; retrieved evidence by reference.</p>
        <div className="table-wrap"><table><thead><tr><th>#</th><th>Task</th><th>Status</th><th>Model</th><th>Policy</th><th>ms</th><th>Detail</th></tr></thead><tbody>
          {d.ai_runs.map((r: any) => <tr key={r.id}><td>{r.id}</td><td>{r.task}</td><td><Pill v={r.status} /></td><td className="mono">{r.model} {r.digest}</td><td className="mono">{r.policy}</td><td>{r.latency_ms ?? '—'}</td><td className="subtle">{r.detail}</td></tr>)}</tbody></table></div></div>
      <div className="card"><h2>Audit log</h2><table><tbody>{d.audit.map((a: any, i: number) => <tr key={i}><td>{fmtTime(a.at)}</td><td>{a.actor}</td><td>{a.action}</td><td className="mono subtle">{JSON.stringify(a.detail)}</td></tr>)}</tbody></table></div>
    </>
  )}</Loaded>
}
