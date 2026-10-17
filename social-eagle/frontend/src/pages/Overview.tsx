import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs } from '../api'
import { Bars, Coverage, LineChart, Loaded, Stat } from '../ui'
import { useLoad } from '../hooks'

export default function Overview() {
  const [days, setDays] = useState(30)
  const [staff, setStaff] = useState(false)
  const s = useLoad(() => api.get(`/api/overview${qs({ days, include_staff: staff })}`), [days, staff])
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <div><h1>Community overview</h1><div className="subtle">Calculated from synced records with defined metrics (no AI).</div></div>
        <div className="spacer" />
        <div><label htmlFor="days">Period</label>
          <select id="days" value={days} onChange={e => setDays(Number(e.target.value))}>
            {[7, 14, 30, 60, 90].map(d => <option key={d} value={d}>Last {d} days</option>)}
          </select></div>
        <div><label><input type="checkbox" checked={staff} onChange={e => setStaff(e.target.checked)} /> Include staff activity</label></div>
      </div>
      <Loaded s={s}>{d => {
        const c = d.contributions, m = d.members, sup = d.support
        const labels = Object.keys(c.daily)
        return (
          <>
            <div className="grid cols-4" style={{ marginBottom: 14 }}>
              <Stat label="Active members" value={m.active_members} hint={`${m.joined_in_range} joined · ${m.left_in_range} left in period`} />
              <Stat label="Distinct contributors" value={c.distinct_contributors} hint="posted, commented or reacted" />
              <Stat label="Posts / comments" value={`${c.posts} / ${c.comments}`} hint={`${c.reactions} reactions`} />
              <Stat label="Appear unanswered" value={<Link to="/inbox">{sup.unanswered_now}</Link>} hint="no reply from anyone but the asker" />
              <Stat label="Pending actions" value={<Link to="/review">{d.pending_actions}</Link>} hint="drafts / queued / held" />
              <Stat label="Median first response" value={sup.first_response.median_hours != null ? `${sup.first_response.median_hours} h` : 'n/a'} hint={`${sup.first_response.n} answered questions in period`} />
            </div>
            <div className="grid cols-2">
              <div className="card">
                <h2>Daily participation (IST days)</h2>
                <LineChart incompleteLast={d.coverage?.notes?.some((n: string) => n.includes('incomplete'))} labels={labels} series={[
                  { name: 'Comments', values: labels.map(k => c.daily[k].comments), color: '#a4161a' },
                  { name: 'Posts', values: labels.map(k => c.daily[k].posts), color: '#2a2a2c' },
                  { name: 'Contributors', values: labels.map(k => c.daily[k].contributors), color: '#8a8f99' },
                ]} />
                <div className="subtle">Contribution days measure posting/reacting, not time online or learning.</div>
              </div>
              <div className="card">
                <h2>Unanswered questions by age</h2>
                <Bars rows={Object.entries(sup.unanswered_aging).map(([k, v]) => ({ label: k, value: v as number }))} />
                <h3 style={{ marginTop: 14 }}>Members by tier (synthetic tiers)</h3>
                <Bars rows={Object.entries(m.by_tier).map(([k, v]) => ({ label: k, value: v as number }))} />
                <div className="subtle" style={{ marginTop: 8 }}>Staff/bot activity reported separately: {c.separate.staff_posts_and_comments} staff and {c.separate.bot_posts_and_comments} bot posts/comments.</div>
              </div>
            </div>
            <Coverage c={d.coverage} />
          </>
        )
      }}</Loaded>
    </>
  )
}
