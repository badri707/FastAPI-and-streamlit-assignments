import { type ReactNode } from 'react'
import { fmtTime } from './api'

export function Loading({ what = 'Loading…' }: { what?: string }) { return <div className="loading" role="status">{what}</div> }
export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return <div className="notice error" role="alert">{error} {onRetry && <button onClick={onRetry}>Retry</button>}</div>
}
export function Empty({ children }: { children: ReactNode }) { return <div className="empty">{children}</div> }
export function Notice({ kind = 'info', children }: { kind?: 'info' | 'warn' | 'error' | 'ok'; children: ReactNode }) {
  return <div className={`notice ${kind}`}>{children}</div>
}

export function Loaded<T>({ s, children }: { s: { data: T | null; error: string | null; loading: boolean; reload: () => void }; children: (d: T) => ReactNode }) {
  if (s.error) return <ErrorBox error={s.error} onRetry={s.reload} />
  if (s.loading && !s.data) return <Loading />
  if (!s.data) return <Empty>No data.</Empty>
  return <>{children(s.data)}</>
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return <div className="stat"><div className="v">{value ?? '—'}</div><div className="l">{label}</div>{hint && <div className="h">{hint}</div>}</div>
}

const STATE_KIND: Record<string, string> = {
  ok: 'ok', verified: 'ok', sent: 'ok', alive: 'ok', succeeded: 'ok', resolved: 'ok', answered: 'ok', approved: 'info', queued: 'info',
  drafted: 'info', idle: 'ok', running: 'info', sending: 'info', leased: 'info', partial: 'warn', held: 'warn', unknown_outcome: 'warn',
  open: 'warn', assigned: 'info', unresponsive: 'bad', failed: 'bad', error: 'bad', auth_expired: 'bad', rejected: 'bad', cancelled: '',
  expired: '', never_started: 'warn', stopped: 'warn', unreachable: 'bad', model_missing: 'bad', unavailable: 'bad',
  conflict: 'warn', abstain: 'warn', restricted: 'warn', blocked: 'bad', escalate: 'warn', clarify: 'info', unverified: 'warn',
}
export function Pill({ v, kind }: { v: ReactNode; kind?: string }) {
  const k = kind ?? STATE_KIND[String(v)] ?? ''
  return <span className={`pill ${k}`}>{v}</span>
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="row" style={{ marginTop: 10 }}>
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Prev</button>
      <span className="subtle">Page {page} of {pages} · {total} total</span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
    </div>
  )
}

// Minimal accessible SVG charts (no chart library).
export function LineChart({ series, height = 180, labels, incompleteLast = false }: { series: { name: string; values: number[]; color: string }[]; height?: number; labels: string[]; incompleteLast?: boolean }) {
  const w = 720, h = height, pad = 30
  const max = Math.max(1, ...series.flatMap(s => s.values))
  const n = Math.max(1, labels.length - 1)
  const x = (i: number) => pad + (i / n) * (w - pad * 2)
  const y = (v: number) => h - pad - (v / max) * (h - pad * 2)
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Line chart of ${series.map(s => s.name).join(', ')}`} style={{ width: '100%', height: 'auto' }}>
        <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="#ccc" />
        <text x={4} y={pad} fontSize="10" fill="#777">{max}</text>
        <text x={4} y={h - pad} fontSize="10" fill="#777">0</text>
        {labels.length > 0 && <><text x={pad} y={h - 8} fontSize="10" fill="#777">{labels[0]}</text>
          <text x={w - pad} y={h - 8} fontSize="10" fill="#777" textAnchor="end">{labels[labels.length - 1]}</text></>}
        {series.map(s => {
          const n = s.values.length
          const solid = incompleteLast && n > 1 ? s.values.slice(0, n - 1) : s.values
          return (
            <g key={s.name}>
              <polyline fill="none" stroke={s.color} strokeWidth="2" points={solid.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />
              {incompleteLast && n > 1 && <line x1={x(n - 2)} y1={y(s.values[n - 2])} x2={x(n - 1)} y2={y(s.values[n - 1])} stroke={s.color} strokeWidth="2" strokeDasharray="4 4" />}
            </g>
          )
        })}
        {incompleteLast && <text x={w - pad} y={pad - 8} fontSize="10" fill="#777" textAnchor="end">last day incomplete (dashed)</text>}
      </svg>
      <figcaption className="subtle" style={{ display: 'flex', gap: 14 }}>
        {series.map(s => <span key={s.name}><span style={{ display: 'inline-block', width: 10, height: 10, background: s.color, marginRight: 4 }} />{s.name}</span>)}
      </figcaption>
    </figure>
  )
}

export function Bars({ rows, max }: { rows: { label: string; value: number; note?: string }[]; max?: number }) {
  const m = max ?? Math.max(1, ...rows.map(r => r.value))
  return (
    <div role="list">
      {rows.map(r => (
        <div key={r.label} role="listitem" style={{ display: 'grid', gridTemplateColumns: 'minmax(120px, 34%) 1fr 64px', gap: 8, alignItems: 'center', margin: '4px 0' }}>
          <span style={{ fontSize: '0.86rem' }}>{r.label}</span>
          <div style={{ background: '#efebe4', borderRadius: 4, height: 14 }}>
            <div style={{ width: `${(r.value / m) * 100}%`, background: 'var(--crimson)', height: 14, borderRadius: 4 }} />
          </div>
          <span className="subtle" style={{ textAlign: 'right' }}>{r.value}{r.note ? ` ${r.note}` : ''}</span>
        </div>
      ))}
    </div>
  )
}

export function Coverage({ c }: { c?: { notes?: string[]; last_sync?: string | null; sync_status?: string } | null }) {
  if (!c) return null
  return (
    <div className="subtle" style={{ marginTop: 6 }}>
      Source sync: <Pill v={c.sync_status ?? 'unknown'} /> {c.last_sync ? `last ${fmtTime(c.last_sync)}` : ''}
      {c.notes && c.notes.length > 0 && <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>{c.notes.map(n => <li key={n}>{n}</li>)}</ul>}
    </div>
  )
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, string][]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? 'active' : ''} onClick={() => onChange(k)}>{l}</button>)}
    </div>
  )
}

