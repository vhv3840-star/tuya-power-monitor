export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {credentials: 'same-origin', ...options, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'TuyaMonitor', ...options.headers}})
  if (!response.ok) {
    if (response.status === 401 && path.startsWith('/api')) window.dispatchEvent(new Event('auth-expired'))
    const body = await response.json().catch(() => ({}))
    const message = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((e: {msg:string}) => e.msg).join('; ') : `Ошибка запроса (${response.status})`
    throw new Error(message + (typeof body.hint==='string' ? ' '+body.hint : ''))
  }
  return response.json()
}
export function send<T = {ok: boolean}>(path: string, body?: unknown, method = 'POST') {
  return api<T>(path, {method, body: body === undefined ? undefined : JSON.stringify(body)})
}
