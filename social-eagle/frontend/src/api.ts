// Same-origin API client. Sends the per-session CSRF token on every unsafe request.
let csrf: string | null = null
export const setCsrf = (t: string | null) => { csrf = t }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {}
  if (method !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method, headers, credentials: 'same-origin',
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const j = await res.json()
      msg = typeof j.detail === 'string' ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join('; ') : msg
    } catch { /* non-JSON error body */ }
    if (res.status === 401) window.dispatchEvent(new Event('se-unauthorized'))
    throw new ApiError(res.status, msg)
  }
  const ct = res.headers.get('content-type') || ''
  return (ct.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

export const api = {
  get: <T = any>(p: string) => request<T>('GET', p),
  post: <T = any>(p: string, b?: unknown) => request<T>('POST', p, b ?? {}),
  put: <T = any>(p: string, b: unknown) => request<T>('PUT', p, b),
  patch: <T = any>(p: string, b: unknown) => request<T>('PATCH', p, b),
  del: <T = any>(p: string) => request<T>('DELETE', p),
  form: <T = any>(p: string, f: FormData) => request<T>('POST', p, f, true),
}

export const qs = (o: Record<string, unknown>) => {
  const p = new URLSearchParams()
  Object.entries(o).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, String(v)) })
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' IST'
}
export function fmtDate(iso?: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' })
}
