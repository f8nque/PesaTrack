export const CURRENCY = 'KES' // change to your currency
export const money = n => Number(n || 0).toLocaleString(undefined, { style: 'currency', currency: CURRENCY })
export const today = new Date().toLocaleDateString('en-CA') // YYYY-MM-DD, local time
export const month = today.slice(0, 7)
export const monthStart = today.slice(0, 8) + '01'
export const label = c => c.parentName ? c.parentName + ' / ' + c.name : c.name

export async function api(path, method = 'GET', body) {
  const headers = { 'Content-Type': 'application/json' }
  if (localStorage.t && !/^(login|register)/.test(path)) headers.Authorization = 'Token ' + localStorage.t
  const r = await fetch('/api/' + path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  if (r.status === 401) { localStorage.removeItem('t'); location.reload() }
  if (r.status === 204) return null
  const data = await r.json()
  if (!r.ok) throw data
  return data
}
