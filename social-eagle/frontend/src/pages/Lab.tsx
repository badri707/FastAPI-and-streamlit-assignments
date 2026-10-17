import { useState } from 'react'
import { api } from '../api'
import { Loaded, Notice, Pill } from '../ui'
import { useAction, useLoad } from '../hooks'

// Evaluation lab: inject synthetic events into the stateful local simulator, then watch the real pipeline react.
export default function Lab() {
  const st = useLoad(() => api.get('/api/lab/state'), [])
  const cat = useLoad(() => api.get('/api/lab/catalog'), [])
  const act = useAction()
  const [last, setLast] = useState<any>(null)
  const [q, setQ] = useState({ member_upstream_id: 'syn-mem-scn-samename-a', title: 'How should I start my reels?', body: 'My reels lose viewers in the first seconds. How should I open them?' })
  const [pr, setPr] = useState({ member_upstream_id: 'syn-mem-scn-commenter', lesson_upstream_id: 'crs-onboarding-l2', completed: true })
  const [rx, setRx] = useState({ post_upstream_id: '', member_upstream_id: 'syn-mem-scn-silent' })
  const [ev, setEv] = useState({ event_upstream_id: '', member_upstream_id: 'syn-mem-scn-new', attend: false, minutes: '' })
  const [fault, setFault] = useState({ kind: 'timeout_after_send', remaining: 1 })
  const [adv, setAdv] = useState(60)
  const go = (path: string, body: unknown, ok: string) => act.run(async () => { const r = await api.post(path, body); setLast(r); st.reload() }, ok)
  return (
    <>
      <h1>Evaluation lab</h1>
      <Notice kind="warn">Every control here changes only the SYNTHETIC local simulator. Changes go through the same sync, database, AI, policy and job pipeline as real data would. Fault injection is labelled and controlled.</Notice>
      {act.view}
      <div className="grid cols-2">
        <div className="card"><h2>Add a question</h2>
          <label htmlFor="qm">Member source ID</label><input id="qm" value={q.member_upstream_id} onChange={e => setQ({ ...q, member_upstream_id: e.target.value })} style={{ width: '100%' }} />
          <label htmlFor="qt">Title</label><input id="qt" value={q.title} onChange={e => setQ({ ...q, title: e.target.value })} style={{ width: '100%' }} />
          <label htmlFor="qb">Body</label><textarea id="qb" value={q.body} onChange={e => setQ({ ...q, body: e.target.value })} />
          <button className="primary" disabled={act.busy} onClick={() => go('/api/lab/question', q, 'Question posted in the simulator and synced. The worker will evaluate it (AI) — watch the inbox and review queue.')}>Post question</button>
          <p className="subtle">Scenario IDs: syn-mem-scn-new, -silent, -commenter (general tier), -support, -annual-asker (annual), -injector, -samename-a/-b.</p></div>
        <div className="card"><h2>Change lesson progress</h2>
          <label htmlFor="pm">Member source ID</label><input id="pm" value={pr.member_upstream_id} onChange={e => setPr({ ...pr, member_upstream_id: e.target.value })} style={{ width: '100%' }} />
          <label htmlFor="pl">Lesson</label>
          <Loaded s={cat}>{c => <select id="pl" value={pr.lesson_upstream_id} onChange={e => setPr({ ...pr, lesson_upstream_id: e.target.value })} style={{ width: '100%' }}>{c.lessons.map((l: any) => <option key={l.upstream_id} value={l.upstream_id}>{l.upstream_id} — {l.title}</option>)}</select>}</Loaded>
          <label><input type="checkbox" checked={pr.completed} onChange={e => setPr({ ...pr, completed: e.target.checked })} /> Mark complete (untick to un-mark)</label>
          <button className="primary" disabled={act.busy} onClick={() => go('/api/lab/progress', pr, 'Progress event recorded and synced. Member, course and report pages now reflect it.')}>Apply progress</button></div>
        <div className="card"><h2>Add a reaction</h2>
          <Loaded s={cat}>{c => <><label htmlFor="rp">Post</label><select id="rp" value={rx.post_upstream_id} onChange={e => setRx({ ...rx, post_upstream_id: e.target.value })} style={{ width: '100%' }}><option value="">Choose…</option>{c.posts.map((p: any) => <option key={p.upstream_id} value={p.upstream_id}>{p.title}</option>)}</select></>}</Loaded>
          <label htmlFor="rm">Member source ID</label><input id="rm" value={rx.member_upstream_id} onChange={e => setRx({ ...rx, member_upstream_id: e.target.value })} style={{ width: '100%' }} />
          <button disabled={act.busy || !rx.post_upstream_id} onClick={() => go('/api/lab/reaction', rx, 'Reaction added and synced.')}>Add like</button></div>
        <div className="card"><h2>Join an event</h2>
          <Loaded s={cat}>{c => <><label htmlFor="ee">Event</label><select id="ee" value={ev.event_upstream_id} onChange={e => setEv({ ...ev, event_upstream_id: e.target.value })} style={{ width: '100%' }}><option value="">Choose…</option>{c.events.map((x: any) => <option key={x.upstream_id} value={x.upstream_id}>{x.title} — {x.starts_at?.slice(0, 10)}</option>)}</select></>}</Loaded>
          <label htmlFor="em">Member source ID</label><input id="em" value={ev.member_upstream_id} onChange={e => setEv({ ...ev, member_upstream_id: e.target.value })} style={{ width: '100%' }} />
          <div className="row"><label><input type="checkbox" checked={ev.attend} onChange={e => setEv({ ...ev, attend: e.target.checked })} /> Also attended</label>
            <div><label htmlFor="emin">Minutes (blank = unknown)</label><input id="emin" type="number" value={ev.minutes} onChange={e => setEv({ ...ev, minutes: e.target.value })} style={{ width: 90 }} /></div></div>
          <button disabled={act.busy || !ev.event_upstream_id} onClick={() => go('/api/lab/event-join', { ...ev, minutes: ev.minutes === '' ? null : Number(ev.minutes) }, 'Registration recorded and synced.')}>Join</button></div>
        <div className="card"><h2>Advance test time</h2>
          <div className="row"><select aria-label="Advance by" value={adv} onChange={e => setAdv(Number(e.target.value))}><option value={60}>1 hour</option><option value={360}>6 hours</option><option value={1440}>1 day</option><option value={10080}>7 days</option></select>
            <button onClick={() => go('/api/system/clock/advance', { advance_minutes: adv }, 'Test clock advanced. Scheduled jobs, ages, quiet hours and expiry use this clock.')}>Advance</button></div></div>
        <div className="card"><h2>Inject a connector fault <Pill v="controlled" kind="warn" /></h2>
          <Loaded s={st}>{s => <>
            <select aria-label="Fault kind" value={fault.kind} onChange={e => setFault({ ...fault, kind: e.target.value })} style={{ width: '100%' }}>{Object.entries(s.fault_kinds).map(([k, v]) => <option key={k} value={k}>{k} — {String(v)}</option>)}</select>
            <div className="row" style={{ marginTop: 6 }}><div><label htmlFor="fr">Times (-1 = until cleared)</label><input id="fr" type="number" value={fault.remaining} onChange={e => setFault({ ...fault, remaining: Number(e.target.value) })} style={{ width: 90 }} /></div>
              <button className="danger" onClick={() => go('/api/lab/fault', fault, 'Fault armed.')}>Inject</button>
              <button onClick={() => act.run(async () => { await api.del('/api/lab/fault'); st.reload() }, 'Faults cleared.')}>Clear all</button>
              <button onClick={() => go('/api/lab/sync-now', {}, 'Sync attempted (see result below).')}>Sync now</button></div>
            <p className="subtle">Active faults: {s.faults.length ? s.faults.map((f: any) => `${f.kind} (${f.remaining})`).join(', ') : 'none'}</p></>}</Loaded></div>
      </div>
      {last && <div className="card"><h2>Last result</h2><pre className="box">{JSON.stringify(last, null, 2)}</pre></div>}
      <Loaded s={st}>{s => (
        <div className="card"><h2>Simulator state</h2>
          <p className="subtle">Seed {s.seed} · history anchor {s.anchor} · {s.note}</p>
          <p>{Object.entries(s.counts).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
          <h3>Simulator write log (what the app "sent")</h3>
          <table><tbody>{s.write_log.map((w: any) => <tr key={w.id}><td>{w.at}</td><td>{w.op}</td><td><Pill v={w.outcome} /></td><td className="mono subtle">{w.client_ref}</td><td className="mono">{w.detail}</td></tr>)}</tbody></table>
        </div>
      )}</Loaded>
    </>
  )
}
