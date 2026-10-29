// Plain formatting helpers (no React).

export function formatDate(iso, withYear = true) {
  if (!iso) return ''
  const opts = { day: 'numeric', month: 'short' }
  if (withYear) opts.year = 'numeric'
  return new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString('en-IN', opts)
}

export function formatDateTime(iso) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "just now", "5 minutes ago", "yesterday" ... */
export function timeAgo(iso) {
  let value = (new Date(iso) - Date.now()) / 1000
  const steps = [[60, 'second'], [60, 'minute'], [24, 'hour'], [7, 'day'], [4.35, 'week'], [12, 'month'], [Infinity, 'year']]
  for (const [size, unit] of steps) {
    if (Math.abs(value) < size) return unit === 'second' ? 'just now' : rtf.format(Math.round(value), unit)
    value /= size
  }
  return ''
}

export function formatMoney(value) {
  if (value === null || value === undefined || value === '') return '—'
  return '₹ ' + Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

export const todayISO = () => new Date().toLocaleDateString('en-CA') // YYYY-MM-DD, local time

// ------------------------------------------------------------ trips
export function dateRange(r) {
  if (!r.end_date) return formatDate(r.start_date)
  const sameYear = r.start_date.slice(0, 4) === r.end_date.slice(0, 4)
  return `${formatDate(r.start_date, !sameYear)} – ${formatDate(r.end_date)}`
}

/** "3 days" for a whole trip (start_date … end_date). */
export function tripLength(r) {
  if (!r.end_date) return 'Same day'
  const days = Math.round((new Date(r.end_date) - new Date(r.start_date)) / 86400000)
  return `${days + 1} days`
}

/** One leg: "Pune → Mumbai" or "Hotel in Delhi". */
export function legRoute(leg) {
  return leg.service === 'HOTEL' ? `Hotel in ${leg.destination}` : `${leg.origin} → ${leg.destination}`
}

/** One leg's date: "12 Nov" or, for hotels, "12 Nov – 14 Nov · 2 nights". */
export function legDates(leg) {
  if (leg.service !== 'HOTEL' || !leg.end_date) return formatDate(leg.date)
  const nights = Math.round((new Date(leg.end_date) - new Date(leg.date)) / 86400000)
  return `${formatDate(leg.date, false)} – ${formatDate(leg.end_date)} · ${nights} night${nights === 1 ? '' : 's'}`
}

// ------------------------------------------------------------ people
export function initials(name = '') {
  return name.split(' ').filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('') || '?'
}

const AVATAR_COLORS = ['#4f46e5', '#0891b2', '#059669', '#d97706', '#db2777', '#7c3aed', '#2563eb', '#dc2626']
export function avatarColor(name = '') {
  let hash = 0
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) | 0
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
}

/** "Chrome on Windows" from a browser user-agent string. */
export function deviceName(ua = '') {
  if (!ua) return 'Unknown device'
  if (/python|curl|httpie|postman/i.test(ua)) return 'Script / API client'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox'
    : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  const os = /Windows/.test(ua) ? 'Windows' : /Mac OS/.test(ua) ? 'macOS' : /Android/.test(ua) ? 'Android'
    : /iPhone|iPad/.test(ua) ? 'iOS' : /Linux/.test(ua) ? 'Linux' : ''
  return os ? `${browser} on ${os}` : browser
}

/** Turns Django's {field: ["message"]} errors into {field: "message"}. */
export function fieldErrors(err) {
  const data = err.status === 400 ? err.data : { non_field_errors: [err.message] }
  return Object.fromEntries(Object.entries(data).map(([k, v]) => [k, [].concat(v).join(' ')]))
}
