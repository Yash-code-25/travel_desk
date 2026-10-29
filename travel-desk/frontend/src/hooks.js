// Reusable React hooks. Each one replaces logic that used to be copied into several components.
import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'

export const PAGE_SIZE = 15 // must match the server's page size (backend/desk/pagination.py)

/** Returns `value` only after it stopped changing for `delay` ms (used for search boxes). */
export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/** Calls `handler` when Esc is pressed, while `active` is true. */
export function useEscape(handler, active = true) {
  const latest = useRef(handler)
  latest.current = handler
  useEffect(() => {
    if (!active) return
    const onKey = (e) => e.key === 'Escape' && latest.current()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [active])
}

/** Calls `handler` on a mouse press outside the element in `ref`, while `active` is true. */
export function useClickOutside(ref, handler, active = true) {
  const latest = useRef(handler)
  latest.current = handler
  useEffect(() => {
    if (!active) return
    const onDown = (e) => !ref.current?.contains(e.target) && latest.current()
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [ref, active])
}

/** Runs `task` now and every `ms` milliseconds, but only while the browser tab is visible. */
export function useVisibleInterval(task, ms, deps = []) {
  const latest = useRef(task)
  latest.current = task
  useEffect(() => {
    const run = () => document.visibilityState === 'visible' && latest.current()
    run()
    const timer = setInterval(run, ms)
    document.addEventListener('visibilitychange', run)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', run) }
  }, [ms, ...deps])
}

/**
 * Loads a paginated list from the server: `{ count, next, previous, results }`.
 * - empty params are left out of the URL
 * - changing params goes back to page 1
 * - a newer request cancels an older one still in flight
 */
export function usePagedList(path, params, reloadKey = 0) {
  const [page, setPage] = useState(1)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const paramsKey = JSON.stringify(params)

  useEffect(() => setPage(1), [paramsKey])

  useEffect(() => {
    const ctrl = new AbortController()
    const query = new URLSearchParams({ ...Object.fromEntries(Object.entries(params).filter(([, v]) => v)), page })
    setLoading(true)
    api(`${path}?${query}`, { signal: ctrl.signal })
      .then((data) => { setResult(data); setError('') })
      .catch((e) => {
        if (e.name === 'AbortError') return
        if (e.status === 404 && page > 1) setPage(1) // that page no longer exists
        else setError(e.message)
      })
      .finally(() => !ctrl.signal.aborted && setLoading(false))
    return () => ctrl.abort()
  }, [path, paramsKey, page, reloadKey])

  return { page, setPage, result, loading, error, rows: result?.results || [] }
}
