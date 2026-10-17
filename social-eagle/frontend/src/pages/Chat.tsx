import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { Notice, Pill } from '../ui'
import { useAction } from '../hooks'

const EXAMPLES = ['How many members joined in the last 14 days?', 'Which questions are still unanswered?', 'Tell me about Kavya Iyer',
  'How many members are in the stalled progress segment?', 'What did the assistant do this week?', 'What is the minimum daily ad budget per ad set?',
  'Compare the last 7 days with the week before', 'Pause all automation']

type Msg = { role: 'user' | 'assistant'; content: string; meta?: any }

export default function Chat() {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [cid, setCid] = useState<string | null>(null)
  const [text, setText] = useState('')
  const act = useAction()
  const send = (q: string) => act.run(async () => {
    setMsgs(m => [...m, { role: 'user', content: q }])
    setText('')
    const r = await api.post('/api/chat', { message: q, conversation_id: cid })
    setCid(r.conversation_id)
    setMsgs(m => [...m, { role: 'assistant', content: r.answer ?? '', meta: r }])
  })
  const submit = (e: FormEvent) => { e.preventDefault(); if (text.trim()) send(text.trim()) }
  return (
    <>
      <h1>Owner chat</h1>
      <Notice>Ask about members, participation, unanswered questions, progress, course content or the assistant's own actions. The model only chooses a read-only tool;
        numbers come from calculated metrics and are checked against the tool result. It cannot run SQL, shell commands or take actions by itself.</Notice>
      <div className="row" style={{ marginBottom: 10 }}>{EXAMPLES.map(e => <button key={e} disabled={act.busy} onClick={() => send(e)}>{e}</button>)}</div>
      <div aria-live="polite">
        {msgs.map((m, i) => <div key={i} className={`chat-msg ${m.role}`}>{m.role === 'user' ? m.content : <Answer m={m} />}</div>)}
        {act.busy && <div className="chat-msg assistant subtle">Thinking with the local model… (CPU-only machines can take 10–60 s)</div>}
      </div>
      {act.view}
      <form onSubmit={submit} className="row" style={{ marginTop: 10 }}>
        <div style={{ flex: 1 }}><label htmlFor="cq">Your question</label><input id="cq" value={text} onChange={e => setText(e.target.value)} style={{ width: '100%' }} maxLength={1000} /></div>
        <button className="primary" disabled={act.busy}>Ask</button>
      </form>
    </>
  )
}

function Answer({ m }: { m: Msg }) {
  const r = m.meta
  const confirm = useAction()
  if (r.status === 'unavailable') return <Notice kind="warn">AI is unavailable: {r.detail}. {r.hint}</Notice>
  return (
    <>
      {r.answer && <div className="ai-box"><div className="ai-label">{r.kind === 'ai_answer_from_knowledge' ? 'AI answer from approved knowledge' : 'AI interpretation'} <Pill v={r.status} /></div>
        <div style={{ whiteSpace: 'pre-wrap' }}>{r.answer}</div>
        {r.citations?.length > 0 && <div className="subtle">Sources: {r.citations.map((c: any) => <a key={c.id} href={c.link} style={{ marginRight: 8 }}>[{c.id}] {c.title}</a>)}</div>}
        {r.reasons?.length > 0 && <div className="subtle">Notes: {r.reasons.join('; ')}</div>}
      </div>}
      {r.detail && <Notice kind="warn">{r.detail}</Notice>}
      {r.data && <details style={{ marginTop: 6 }} open={r.status !== 'ok'}><summary>Calculated data used (tool: {r.tool})</summary><pre className="box facts-box">{JSON.stringify(r.data, null, 2)}</pre></details>}
      {r.confirm_required && <div style={{ marginTop: 6 }}>{confirm.view}
        <button className="danger" onClick={() => confirm.run(() => api.post('/api/system/pause', { paused: r.confirm_required.action === 'pause', reason: 'from owner chat' }), `Confirmed: ${r.confirm_required.action}.`)}>Confirm {r.confirm_required.action}</button></div>}
    </>
  )
}
