import { useCallback, useEffect, useRef, useState } from 'react'
import { Notice } from './ui'

// Data loader hook with loading/error state and manual reload.
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fn, deps)
  const seq = useRef(0)
  const reload = useCallback(() => {
    const mine = ++seq.current // ignore responses from superseded requests (e.g. a slow load finishing after a search)
    setLoading(true)
    setError(null)
    load().then(d => { if (mine === seq.current) { setData(d); setLoading(false) } })
      .catch(e => { if (mine === seq.current) { setError(String(e.message || e)); setLoading(false) } })
  }, [load])
  useEffect(() => { reload() }, [reload])
  return { data, error, loading, reload, setData }
}

export function useAction() {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true); setMsg(null)
    try { await fn(); if (ok) setMsg({ kind: 'ok', text: ok }) } catch (e) { setMsg({ kind: 'error', text: String((e as Error).message) }) }
    setBusy(false)
  }
  const view = msg ? <Notice kind={msg.kind}>{msg.text}</Notice> : null
  return { busy, run, view, setMsg }
}
