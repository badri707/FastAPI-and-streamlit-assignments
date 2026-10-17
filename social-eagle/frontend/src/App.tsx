import { useEffect, useState, type FormEvent } from 'react'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { api, setCsrf } from './api'
import { Notice, Pill } from './ui'
import Overview from './pages/Overview'
import { MemberDetail, Members } from './pages/Members'
import { Inbox, Thread, Discussions } from './pages/Discussions'
import { Knowledge, KnowledgeDoc } from './pages/Knowledge'
import { CourseDetail, EventDetail, Events, Learning } from './pages/Learning'
import { Engagement, Reports } from './pages/Reports'
import Chat from './pages/Chat'
import { Automation, ReviewQueue, ActionDetail } from './pages/Automation'
import { System } from './pages/System'
import Lab from './pages/Lab'
import DataPage from './pages/Data'

type AuthStatus = { enrolled: boolean; enrollment_pending: boolean; signed_in: boolean; username: string | null; csrf: string | null }
type Sys = any

function AuthScreen({ status, onDone }: { status: AuthStatus; onDone: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const enroll = !status.enrolled
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null)
    try {
      const r = enroll ? await api.post('/api/auth/enroll', { token, username, password }) : await api.post('/api/auth/login', { username, password })
      setCsrf(r.csrf)
      onDone()
    } catch (x) { setErr((x as Error).message) }
  }
  return (
    <div className="auth-wrap">
      <div className="card">
        <h1>Social Eagle Community Manager</h1>
        <p className="subtle">Local admin console · Evaluation build</p>
        {enroll && <Notice>First run: create the admin account. Paste the one-time enrollment token printed by <code>scripts/start</code>
          (also saved in <code>data/enrollment.token</code>). There are no default credentials.</Notice>}
        <form onSubmit={submit}>
          {enroll && <div style={{ marginBottom: 10 }}><label htmlFor="tok">Enrollment token</label><input id="tok" value={token} onChange={e => setToken(e.target.value)} style={{ width: '100%' }} required /></div>}
          <div style={{ marginBottom: 10 }}><label htmlFor="u">Username</label><input id="u" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} style={{ width: '100%' }} required /></div>
          <div style={{ marginBottom: 10 }}><label htmlFor="p">Password {enroll && '(min 10 characters)'}</label><input id="p" type="password" autoComplete={enroll ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} style={{ width: '100%' }} required /></div>
          {err && <Notice kind="error">{err}</Notice>}
          <button className="primary" type="submit">{enroll ? 'Create admin account' : 'Sign in'}</button>
        </form>
      </div>
    </div>
  )
}

function StatusBar({ sys }: { sys: Sys | null }) {
  if (!sys) return null
  const sync = sys.sync?.[0]
  return (
    <div className="statusbar" aria-label="System status">
      <span>Worker <Pill v={sys.worker.state} /></span>
      <span>Sync <Pill v={sync ? sync.status : 'never'} /></span>
      <span>Connection <Pill v={sys.connection.status} /></span>
      <span>AI <Pill v={sys.ai.status} /></span>
      <span>Queue <Pill v={`${(sys.queue.queued ?? 0) + (sys.queue.leased ?? 0)} pending`} kind="info" /></span>
      {sys.paused && <Pill v="AUTOMATION PAUSED" kind="bad" />}
      {sys.disk.low && <Pill v="LOW DISK" kind="bad" />}
      <span className="subtle">Test clock: {sys.clock.local}</span>
    </div>
  )
}

const NAV: [string, string, string?][] = [
  ['/', 'Overview'], ['', 'Community', 's'], ['/members', 'Members'], ['/inbox', 'Support inbox'], ['/discussions', 'Discussions'],
  ['/learning', 'Learning'], ['/events', 'Events'], ['/engagement', 'Engagement'], ['', 'Assistant', 's'], ['/chat', 'Owner chat'],
  ['/review', 'Review queue & actions'], ['/automation', 'Automation rules'], ['/knowledge', 'Knowledge'], ['', 'Operations', 's'],
  ['/reports', 'Reports'], ['/data', 'Import & backups'], ['/lab', 'Evaluation lab'], ['/system', 'System & settings'],
]

export default function App() {
  const [status, setStatus] = useState<AuthStatus | null>(null)
  const [sys, setSys] = useState<Sys | null>(null)
  const refreshAuth = () => api.get<AuthStatus>('/api/auth/status').then(s => { setCsrf(s.csrf); setStatus(s) }).catch(() => setStatus(null))
  useEffect(() => {
    refreshAuth()
    const h = () => refreshAuth()
    window.addEventListener('se-unauthorized', h)
    return () => window.removeEventListener('se-unauthorized', h)
  }, [])
  useEffect(() => {
    if (!status?.signed_in) return
    const tick = () => api.get('/api/system/status').then(setSys).catch(() => { /* surfaced by pages */ })
    tick()
    const t = setInterval(tick, 10000)
    return () => clearInterval(t)
  }, [status?.signed_in])

  const banner = (
    <div className="eval-banner" role="note">
      Evaluation — synthetic community data
      <span>All delivery is simulated locally · Live Skool connection deferred until approval</span>
    </div>
  )
  if (!status) return <>{banner}<p className="loading">Connecting to the local server…</p></>
  if (!status.signed_in) return <>{banner}<AuthScreen status={status} onDone={refreshAuth} /></>
  return (
    <BrowserRouter>
      {banner}
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">Social Eagle<small>Community Manager · local</small></div>
          <nav aria-label="Main">
            {NAV.map(([to, label, kind]) => kind === 's'
              ? <div className="section" key={label}>{label}</div>
              : <NavLink key={to} to={to} end={to === '/'}>{label}</NavLink>)}
          </nav>
          <div style={{ padding: '18px 10px', fontSize: '0.78rem', color: '#aaa' }}>
            Signed in as {status.username}<br />
            <button style={{ marginTop: 6 }} onClick={() => api.post('/api/auth/logout').then(refreshAuth)}>Sign out</button>
          </div>
        </aside>
        <main className="main">
          <StatusBar sys={sys} />
          {sys?.worker?.state && sys.worker.state !== 'alive' && <Notice kind="warn">The background worker is {sys.worker.state.replace('_', ' ')}. Sync, automation and sending are paused until it runs (<code>scripts/start</code>). This app only works while this computer is awake.</Notice>}
          {sys?.connection && !sys.connection.ok && <Notice kind="error">Community connection problem: {sys.connection.detail ?? sys.connection.status}. Figures may be stale — this is not an empty community.</Notice>}
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/members" element={<Members />} />
            <Route path="/members/:id" element={<MemberDetail />} />
            <Route path="/inbox" element={<Inbox />} />
            <Route path="/discussions" element={<Discussions />} />
            <Route path="/discussions/:id" element={<Thread />} />
            <Route path="/learning" element={<Learning />} />
            <Route path="/learning/:id" element={<CourseDetail />} />
            <Route path="/events" element={<Events />} />
            <Route path="/events/:id" element={<EventDetail />} />
            <Route path="/engagement" element={<Engagement />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/review" element={<ReviewQueue />} />
            <Route path="/review/:id" element={<ActionDetail />} />
            <Route path="/automation" element={<Automation />} />
            <Route path="/knowledge" element={<Knowledge />} />
            <Route path="/knowledge/:id" element={<KnowledgeDoc />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/data" element={<DataPage />} />
            <Route path="/lab" element={<Lab />} />
            <Route path="/system" element={<System sys={sys} />} />
            <Route path="*" element={<Notice>Page not found.</Notice>} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
