// One helper for every call to Django.
// - sends the CSRF token on POST/PUT (Django requires it for logged-in users)
// - sends JSON, or FormData when uploading a file
// - supports AbortController `signal` so an old search can be cancelled by a newer one
// - throws an Error with a readable message + the field errors from Django

function getCookie(name) {
  const row = document.cookie.split('; ').find((c) => c.startsWith(name + '='))
  return row ? decodeURIComponent(row.split('=')[1]) : ''
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  const headers = { Accept: 'application/json' }
  let payload = body

  if (method !== 'GET') headers['X-CSRFToken'] = getCookie('csrftoken')
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch('/api' + path, { method, headers, body: payload, signal, credentials: 'same-origin' })
  } catch (e) {
    if (e.name === 'AbortError') throw e
    throw Object.assign(new Error('Cannot reach the server. Check that Django is running.'), { status: 0, data: {} })
  }

  const data = res.status === 204 ? null : await res.json().catch(() => null)
  // 401 = no valid session (expired, revoked by an admin, account deactivated): App shows the sign-in page.
  if (res.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('auth:expired'))
  if (!res.ok) {
    const err = new Error(firstError(data) || `Something went wrong (${res.status}).`)
    err.status = res.status
    err.data = data || {}
    throw err
  }
  return data
}

// Pick the most useful message out of Django's error JSON.
export function firstError(data) {
  if (!data) return ''
  if (typeof data.detail === 'string') return data.detail
  if (data.non_field_errors) return data.non_field_errors[0]
  const key = Object.keys(data)[0]
  if (!key) return ''
  return Array.isArray(data[key]) ? data[key][0] : String(data[key])
}

// All messages at once (e.g. booking: missing PNR AND missing ticket).
export function allErrors(err) {
  if (err.status !== 400) return err.message
  const list = Object.values(err.data).flat().filter((v) => typeof v === 'string')
  return list.length ? list.join(' ') : err.message
}
