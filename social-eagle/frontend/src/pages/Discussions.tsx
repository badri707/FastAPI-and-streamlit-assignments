import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmtTime, qs } from '../api'
import { Empty, Loaded, Notice, Pager, Pill, Tabs } from '../ui'
import { useAction, useLoad } from '../hooks'

export function Inbox() {
  const [tab, setTab] = useState('unanswered')
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const filters: Record<string, Record<string, unknown>> = {
    unanswered: { unanswered: true }, open: { status: 'open,assigned,drafted' }, support: { label: 'needs_support', status: 'open,assigned,drafted' },
    answered: { status: 'answered' }, resolved: { status: 'resolved,dismissed' }, all: {},
  }
  const s = useLoad(() => api.get(`/api/support${qs({ ...filters[tab], q, page })}`), [tab, page, q])
  const topics = useLoad(() => api.get('/api/support/topics'), [])
  const act = useAction()
  const [summary, setSummary] = useState<Record<string, any>>({})
  return (
    <>
      <h1>Support inbox</h1>
      <div className="subtle">Labels from transparent rules (<code>rule:v1</code>) or staff (<code>manual</code>) are shown with their source. "Appears unanswered" is an observed thread fact; "resolved" is human-verified only.</div>
      <Tabs value={tab} onChange={v => { setTab(v); setPage(1) }} tabs={[['unanswered', 'Appear unanswered'], ['support', 'Needs support'], ['open', 'All open'],
        ['answered', 'Answered (not verified)'], ['resolved', 'Resolved'], ['all', 'All']]} />
      <div className="row" style={{ marginBottom: 8 }}><div><label htmlFor="iq">Filter text</label><input id="iq" value={q} onChange={e => { setPage(1); setQ(e.target.value) }} /></div></div>
      {act.view}
      <Loaded s={s}>{d => (
        <div className="card">
          {d.rows.length === 0 ? <Empty>Nothing here.</Empty> : <div className="table-wrap"><table>
            <thead><tr><th>Question</th><th>Asked by</th><th>Age</th><th>Label</th><th>Status</th><th>Assignee</th><th>Reply</th><th></th></tr></thead>
            <tbody>{d.rows.map((r: any) => (
              <tr key={r.id}>
                <td><Link to={`/discussions/${r.post.id}`}>{r.post.title || r.post.body.slice(0, 60)}</Link>{r.priority === 'high' && <> <Pill v="high" kind="bad" /></>}
                  <div className="subtle">{r.post.category}</div></td>
                <td>{r.post.author ? <Link to={`/members/${r.post.author.id}`}>{r.post.author.name}</Link> : '—'}</td>
                <td>{r.age_hours < 48 ? `${r.age_hours} h` : `${Math.round(r.age_hours / 24)} d`}</td>
                <td>{r.label} <div className="subtle">{r.label_source}</div></td>
                <td><Pill v={r.status} />{r.appears_unanswered && <div className="subtle">unanswered</div>}</td>
                <td>{r.assignee ?? '—'}</td>
                <td>{r.pending_action ? <Link to={`/review/${r.pending_action.id}`}><Pill v={r.pending_action.state} /></Link> : '—'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button disabled={act.busy} onClick={() => act.run(async () => { const j = await api.post(`/api/support/${r.id}/draft`); s.reload(); return j }, 'Draft requested — the worker will prepare it with the local model. Check the review queue shortly.')}>Draft reply</button>{' '}
                  <button disabled={act.busy} onClick={() => act.run(async () => { await api.patch(`/api/support/${r.id}`, { assignee: 'owner' }); s.reload() })}>Assign to me</button>
                </td>
              </tr>))}
            </tbody></table></div>}
          <Pager page={page} pageSize={50} total={d.total} onPage={setPage} />
        </div>
      )}</Loaded>
      <div className="card">
        <h2>Repeated questions by topic</h2>
        <Loaded s={topics}>{t => (
          <>
            <div className="subtle" style={{ marginBottom: 8 }}>{t.coverage}</div>
            <table><thead><tr><th>Topic (best-matching material)</th><th>Questions</th><th>Unanswered</th><th>Examples</th><th>AI summary</th></tr></thead><tbody>
              {t.topics.slice(0, 15).map((g: any) => (
                <tr key={g.topic}><td>{g.topic}</td><td>{g.count}</td><td>{g.unanswered}</td><td className="subtle">{g.examples.join(' · ')}</td>
                  <td style={{ minWidth: 220 }}>{summary[g.topic] ? (summary[g.topic].status === 'ok'
                    ? <div className="ai-box"><div className="ai-label">AI suggestion</div>{summary[g.topic].summary}<div className="subtle">Suggested FAQ: {summary[g.topic].suggested_faq}</div></div>
                    : <Notice kind="warn">AI unavailable: {summary[g.topic].detail}</Notice>)
                    : <button onClick={() => act.run(async () => { const r = await api.post('/api/support/topics/summary', { topic: g.topic }); setSummary(x => ({ ...x, [g.topic]: r })) })}>Summarise</button>}</td></tr>))}
            </tbody></table>
          </>
        )}</Loaded>
      </div>
    </>
  )
}

function Node({ n }: { n: any }) {
  return (
    <div className={`thread-node ${n.author?.is_bot || n.is_automated ? 'bot' : ''}`} id={`post-${n.id}`}>
      <div className="meta">
        <strong>{n.author ? <Link to={`/members/${n.author.id}`}>{n.author.name}</Link> : 'unknown'}</strong>
        {n.author?.is_staff && <> <Pill v="staff" kind="info" /></>}{(n.author?.is_bot || n.is_automated) && <> <Pill v="automated" kind="bad" /></>}
        {' '}· {fmtTime(n.created_at)}{n.edited_at && ` · edited (v${n.version})`}{n.deleted && <> <Pill v="deleted" /></>} · {n.reactions} ♥
      </div>
      {n.title && <h3 style={{ margin: '4px 0' }}>{n.title}</h3>}
      <div className="body">{n.deleted ? <em className="subtle">[deleted at source]</em> : n.body}</div>
      {n.children.map((c: any) => <Node key={c.id} n={c} />)}
    </div>
  )
}

export function Thread() {
  const { id } = useParams()
  const s = useLoad(() => api.get(`/api/threads/${id}`), [id])
  const act = useAction()
  const [reply, setReply] = useState('')
  const [note, setNote] = useState('')
  const { reload } = s
  useEffect(() => { const t = setInterval(reload, 15000); return () => clearInterval(t) }, [reload])
  return (
    <Loaded s={s}>{d => {
      const it = d.support_item
      const patch = (b: Record<string, unknown>) => act.run(async () => { await api.patch(`/api/support/${it.id}`, b); s.reload() }, 'Updated.')
      const send = (e: FormEvent) => { e.preventDefault(); act.run(async () => { await api.post(`/api/support/${it.id}/reply`, { body: reply }); setReply(''); s.reload() }, 'Your reply was approved and queued for (simulated) delivery.') }
      return (
        <>
          <Link to="/inbox">‹ Inbox</Link>
          <Notice>{d.provenance}</Notice>
          <div className="card"><Node n={d.thread} /></div>
          {act.view}
          {it && <div className="card">
            <h2>Support item <Pill v={it.status} /></h2>
            <div className="subtle">Label <strong>{it.label}</strong> ({it.label_source}{it.human_verified ? ', human-verified' : ''}) · priority {it.priority} ·
              first response {it.first_response_at ? `${fmtTime(it.first_response_at)} by ${it.first_response_by}` : 'none yet'}{it.resolved_at && ` · resolved ${fmtTime(it.resolved_at)}`}</div>
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={() => act.run(async () => { await api.post(`/api/support/${it.id}/draft`); s.reload() }, 'Draft requested (worker + local model). It will appear below and in the review queue.')}>Generate AI draft</button>
              <button onClick={() => patch({ assignee: 'owner' })}>Assign to me</button>
              <select aria-label="Set label" value={it.label} onChange={e => patch({ label: e.target.value })}>
                {['question', 'needs_support', 'ambiguous', 'not_question'].map(l => <option key={l}>{l}</option>)}</select>
              <button onClick={() => patch({ priority: it.priority === 'high' ? 'normal' : 'high' })}>Toggle priority</button>
              <button onClick={() => patch({ status: 'dismissed' })}>Dismiss</button>
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <div style={{ flex: 1 }}><label htmlFor="rn">Resolution note (marks human-verified resolved)</label><input id="rn" value={note} onChange={e => setNote(e.target.value)} style={{ width: '100%' }} /></div>
              <button className="primary" onClick={() => patch({ status: 'resolved', resolution_note: note })}>Mark resolved</button>
            </div>
            <form onSubmit={send} style={{ marginTop: 12 }}>
              <label htmlFor="reply">Write a staff reply (published to the local simulator thread)</label>
              <textarea id="reply" value={reply} onChange={e => setReply(e.target.value)} required maxLength={5000} />
              <button className="primary" disabled={act.busy}>Approve & send reply</button>
            </form>
          </div>}
          <div className="card">
            <h2>Action history for this thread</h2>
            {d.actions.length === 0 ? <Empty>No actions yet.</Empty> : <table><tbody>{d.actions.map((a: any) => (
              <tr key={a.id}><td><Link to={`/review/${a.id}`}>Action #{a.id}</Link></td><td><Pill v={a.state} /></td><td>{a.origin}</td>
                <td>{a.simulated ? 'simulated delivery' : 'live'}</td><td>{fmtTime(a.created_at)}</td><td className="mono">{a.remote_id ?? ''}</td></tr>))}</tbody></table>}
          </div>
        </>
      )
    }}</Loaded>
  )
}

export function Discussions() {
  const [cat, setCat] = useState('')
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(1)
  const s = useLoad(() => api.get(`/api/posts${qs({ category: cat, q: term, page })}`), [cat, term, page])
  return (
    <>
      <h1>Discussions</h1>
      <form className="row" style={{ marginBottom: 10 }} onSubmit={e => { e.preventDefault(); setPage(1); setTerm(q) }}>
        <div><label htmlFor="dq">Full-text search</label><input id="dq" value={q} onChange={e => setQ(e.target.value)} /></div>
        <Loaded s={s}>{d => <div><label htmlFor="dc">Category</label><select id="dc" value={cat} onChange={e => { setPage(1); setCat(e.target.value) }}><option value="">All</option>{d.categories.map((c: string) => <option key={c}>{c}</option>)}</select></div>}</Loaded>
        <button>Search</button>
      </form>
      <Loaded s={s}>{d => (
        <div className="card">
          {d.rows.length === 0 ? <Empty>No posts found.</Empty> : <table><thead><tr><th>Post</th><th>Author</th><th>Category</th><th>Comments</th><th>♥</th><th>Posted</th></tr></thead><tbody>
            {d.rows.map((p: any) => <tr key={p.id}><td><Link to={p.link}>{p.title || p.body.slice(0, 60)}</Link>{p.deleted && <> <Pill v="deleted" /></>}</td>
              <td>{p.author?.name}</td><td>{p.category}</td><td>{p.comment_count}</td><td>{p.reactions}</td><td>{fmtTime(p.created_at)}</td></tr>)}
          </tbody></table>}
          <Pager page={page} pageSize={30} total={d.total} onPage={setPage} />
        </div>
      )}</Loaded>
    </>
  )
}
