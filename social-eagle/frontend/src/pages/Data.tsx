import { useState, type FormEvent } from 'react'
import { api, fmtTime } from '../api'
import { Empty, Loaded, Notice, Pill } from '../ui'
import { useAction, useLoad } from '../hooks'

export default function DataPage() {
  const act = useAction()
  const batches = useLoad(() => api.get('/api/import/batches'), [])
  const backups = useLoad(() => api.get('/api/backups'), [])
  const [preview, setPreview] = useState<any>(null)
  const [verify, setVerify] = useState<any>(null)
  const doPreview = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const f = new FormData(e.currentTarget)
    act.run(async () => setPreview(await api.form('/api/import/preview', f)))
  }
  return (
    <>
      <h1>Import & backups</h1>
      {act.view}
      <div className="card">
        <h2>Optional import (CSV / JSON)</h2>
        <Notice>Not required for evaluation — the synthetic community is sufficient. Imported rows are stored in their own group with a dataset label and are never mixed into synthetic statistics unless explicitly selected.</Notice>
        <form className="row" onSubmit={doPreview}>
          <div><label htmlFor="if">File (.csv or .json, UTF-8, max 10 MB)</label><input id="if" name="file" type="file" accept=".csv,.json" required /></div>
          <div><label htmlFor="ie">Entity</label><select id="ie" name="entity"><option>members</option><option>posts</option></select></div>
          <button>Preview mapping</button>
        </form>
        {preview && <div style={{ marginTop: 12 }}>
          <h3>Preview — batch #{preview.batch_id} ({preview.format})</h3>
          {preview.duplicate_of_batch && <Notice kind="warn">This identical file was already imported as batch #{preview.duplicate_of_batch}; committing will be refused.</Notice>}
          <p>{preview.rows_total} rows · <Pill v={`${preview.rows_ok} valid`} kind="ok" /> <Pill v={`${preview.rows_rejected} rejected`} kind={preview.rows_rejected ? 'bad' : ''} /></p>
          <table><thead><tr><th>Field</th><th>Required</th><th>Mapped column</th></tr></thead><tbody>
            {Object.entries(preview.schema).map(([f, spec]: any) => <tr key={f}><td>{f}</td><td>{spec.required ? 'yes' : 'no'}</td><td>{preview.mapping[f] ?? <span className="subtle">unmapped</span>}</td></tr>)}</tbody></table>
          {preview.errors.length > 0 && <details><summary>Row errors ({preview.errors.length})</summary><pre className="box">{JSON.stringify(preview.errors, null, 2)}</pre></details>}
          <details><summary>Sample valid rows</summary><pre className="box">{JSON.stringify(preview.sample, null, 2)}</pre></details>
          <p className="subtle">{preview.provenance_note}</p>
          <button className="primary" disabled={preview.rows_ok === 0} onClick={() => act.run(async () => { const r = await api.post(`/api/import/${preview.batch_id}/commit`, {}); setPreview(null); batches.reload(); act.setMsg({ kind: 'ok', text: `Imported ${r.inserted} rows as ${r.dataset} (${r.rejected} rejected). ${r.note}` }) })}>Commit import</button>
        </div>}
        <Loaded s={batches}>{rows => rows.length === 0 ? <Empty>No imports yet.</Empty> : <table style={{ marginTop: 10 }}><thead><tr><th>#</th><th>File</th><th>Entity</th><th>Status</th><th>Rows ok / rejected</th><th>Dataset</th><th>When</th><th></th></tr></thead><tbody>
          {rows.map((b: any) => <tr key={b.id}><td>{b.id}</td><td>{b.filename}</td><td>{b.entity}</td><td><Pill v={b.status} /></td><td>{b.rows_ok} / {b.rows_rejected}</td><td className="mono">{b.dataset ?? '—'}</td><td>{fmtTime(b.created_at)}</td>
            <td>{b.status === 'committed' && <button className="danger" onClick={() => { if (confirm('Delete all rows from this import?')) act.run(async () => { await api.del(`/api/import/${b.id}`); batches.reload() }, 'Import deleted.') }}>Delete</button>}</td></tr>)}</tbody></table>}</Loaded>
      </div>
      <div className="card">
        <h2>Backups</h2>
        <p className="subtle">Consistent SQLite online backups (app + simulator databases) with checksums. A nightly backup runs at 02:00 IST while the worker is running.</p>
        <button className="primary" disabled={act.busy} onClick={() => act.run(async () => { await api.post('/api/backups'); backups.reload() }, 'Backup created.')}>Back up now</button>
        <Loaded s={backups}>{d => (
          <>
            <p className="subtle">Directory <span className="mono">{d.directory}</span> · {d.free_mb} MB free</p>
            {d.backups.length === 0 ? <Empty>No backups yet.</Empty> : <table><thead><tr><th>Backup</th><th>Integrity</th><th>Rows (members/posts/actions)</th><th></th></tr></thead><tbody>
              {d.backups.map((b: any) => <tr key={b.name}><td className="mono">{b.name}</td><td><Pill v={b.integrity_check} kind={b.integrity_check === 'ok' ? 'ok' : 'bad'} /></td>
                <td>{b.row_counts.members} / {b.row_counts.posts} / {b.row_counts.actions}</td>
                <td><button onClick={() => act.run(async () => setVerify(await api.post('/api/backups/verify', { name: b.name })))}>Test restore (separate copy)</button></td></tr>)}</tbody></table>}
          </>
        )}</Loaded>
        {verify && <Notice kind={verify.row_counts_match ? 'ok' : 'error'}>Restored into <span className="mono">{verify.target}</span>: integrity {JSON.stringify(verify.integrity)}, row counts match: {String(verify.row_counts_match)}. The running data was not touched.</Notice>}
      </div>
    </>
  )
}
