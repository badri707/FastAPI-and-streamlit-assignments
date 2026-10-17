import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api, fmtTime } from '../api'
import { Empty, Loaded, Notice, Pill } from '../ui'
import { useAction, useLoad } from '../hooks'

export function Knowledge() {
  const s = useLoad(() => api.get('/api/knowledge/docs'), [])
  const act = useAction()
  const [q, setQ] = useState('')
  const [tier, setTier] = useState('general')
  const [res, setRes] = useState<any>(null)
  const search = (e: FormEvent) => { e.preventDefault(); act.run(async () => setRes(await api.post('/api/knowledge/search', { query: q, tier: tier === 'owner' ? null : tier, owner: tier === 'owner' }))) }
  const upload = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    act.run(async () => { const r = await api.form('/api/knowledge/upload', f); s.reload(); return r }, 'Uploaded. Check its status below (scanned PDFs are marked needs OCR).')
  }
  return (
    <>
      <h1>Knowledge</h1>
      <div className="subtle">Approved course material the assistant may cite. All seeded documents are SYNTHETIC evaluation content.</div>
      {act.view}
      <div className="grid cols-2">
        <div className="card">
          <h2>Retrieval test</h2>
          <form onSubmit={search} className="row">
            <div style={{ flex: 1 }}><label htmlFor="kq">Question</label><input id="kq" value={q} onChange={e => setQ(e.target.value)} style={{ width: '100%' }} minLength={2} required /></div>
            <div><label htmlFor="kt">As tier</label><select id="kt" value={tier} onChange={e => setTier(e.target.value)}><option>general</option><option>annual</option><option>vip</option><option value="owner">owner (all)</option></select></div>
            <button>Search</button>
          </form>
          {res && <>
            {res.restricted_matches.length > 0 && <Notice kind="warn">Also matched (content hidden for this tier): {res.restricted_matches.map((r: any) => r.course_title).join(', ')}</Notice>}
            {res.passages.length === 0 ? <Empty>No permitted passages.</Empty> : res.passages.map((p: any) => (
              <div key={p.chunk_id} className="facts-box" style={{ marginTop: 8 }}><Link to={p.link}>{p.title}</Link> <span className="subtle">v{p.version} · score {p.score}</span><div style={{ fontSize: '0.88rem' }}>{p.text}</div></div>))}
          </>}
        </div>
        <div className="card">
          <h2>Add approved material</h2>
          <form onSubmit={upload}>
            <label htmlFor="kf">File (.md, .txt, text-based .pdf; max 5 MB)</label><input id="kf" name="file" type="file" accept=".md,.markdown,.txt,.pdf" required />
            <div className="row" style={{ marginTop: 8 }}>
              <div><label htmlFor="ka">Access tiers</label><input id="ka" name="access_tiers" defaultValue="*" pattern="(\*|[a-z0-9_-]+(,[a-z0-9_-]+)*)" /></div>
              <div><label htmlFor="ktt">Title</label><input id="ktt" name="title" /></div>
            </div>
            <button className="primary" style={{ marginTop: 8 }}>Upload</button>
          </form>
          <div className="subtle" style={{ marginTop: 8 }}>Re-uploading a changed file with the same name creates a new version and supersedes the old one.</div>
        </div>
      </div>
      <Loaded s={s}>{docs => (
        <div className="card"><div className="table-wrap"><table>
          <thead><tr><th>Document</th><th>Kind</th><th>Access</th><th>Version</th><th>Status</th><th>Chunks</th><th>Updated</th></tr></thead>
          <tbody>{docs.map((d: any) => <tr key={d.id}><td><Link to={`/knowledge/${d.id}`}>{d.title}</Link><div className="mono subtle">{d.doc_key}</div></td><td>{d.kind}</td>
            <td>{d.access_tiers}</td><td>v{d.version}</td><td><Pill v={d.status} kind={d.status === 'approved' ? 'ok' : d.status === 'needs_ocr' ? 'bad' : ''} />{d.status_detail && <div className="subtle">{d.status_detail}</div>}</td>
            <td>{d.chunks}</td><td className="subtle">{d.updated_label}</td></tr>)}</tbody>
        </table></div></div>
      )}</Loaded>
    </>
  )
}

export function KnowledgeDoc() {
  const { id } = useParams()
  const loc = useLocation()
  const s = useLoad(() => api.get(`/api/knowledge/docs/${id}`), [id])
  useEffect(() => { if (loc.hash && s.data) document.getElementById(loc.hash.slice(1))?.scrollIntoView() }, [loc.hash, s.data])
  return (
    <Loaded s={s}>{d => (
      <>
        <Link to="/knowledge">‹ Knowledge</Link>
        <h1>{d.title}</h1>
        <div className="subtle">{d.doc_key} · v{d.version} · <Pill v={d.status} /> · access {d.access_tiers} · {d.source_path} · sha256 {d.sha256}… · added {fmtTime(d.created_at)}</div>
        {d.status_detail && <Notice kind="warn">{d.status_detail}</Notice>}
        {d.chunk_list.map((c: any) => (
          <div key={c.id} id={`chunk-${c.id}`} className="card" style={loc.hash === `#chunk-${c.id}` ? { borderColor: 'var(--crimson)' } : undefined}>
            <div className="subtle">Passage {c.ordinal + 1} · {c.heading} · chunk #{c.id}</div><div style={{ whiteSpace: 'pre-wrap' }}>{c.text}</div></div>))}
        <div className="card"><h3>Versions</h3>{d.versions.map((v: any) => <div key={v.id}><Link to={`/knowledge/${v.id}`}>v{v.version}</Link> <Pill v={v.status} /> {fmtTime(v.created_at)}</div>)}</div>
      </>
    )}</Loaded>
  )
}
