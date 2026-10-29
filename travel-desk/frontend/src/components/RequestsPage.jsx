// My trips / Approvals / Travel desk: one component, configured by `scope` (see PAGES in constants.js).
import { useEffect, useState } from 'react'
import { ArrowUpDown, Inbox, Plus } from 'lucide-react'
import { api } from '../api.js'
import { PAGES, SERVICE_ICON } from '../constants.js'
import { useDebounced, usePagedList } from '../hooks.js'
import { dateRange, routeText, timeAgo, tripLength } from '../utils.js'
import { Alert, Avatar, Badge, Button, EmptyState, Pager, SearchBox, StatCard, StatusBadge } from './ui.jsx'

const SORTS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
  { value: 'travel', label: 'Travel date (soonest)' },
  { value: '-travel', label: 'Travel date (latest)' },
]

export default function RequestsPage({ scope, refreshKey, onOpen, onNewRequest }) {
  const config = PAGES[scope]
  const [cardKey, setCardKey] = useState(config.defaultCard)
  const [search, setSearch] = useState('')
  const [ordering, setOrdering] = useState(scope === 'mine' ? 'newest' : 'travel')
  const [stats, setStats] = useState(null)
  const q = useDebounced(search.trim())
  const card = config.cards.find((c) => c.key === cardKey)
  const showTraveller = scope !== 'mine'

  // Filtering, search, sorting and paging all happen on the server.
  const list = usePagedList('/requests/', {
    scope, ordering, q,
    status: card.statuses?.join(','),
    overdue: card.overdue ? '1' : '',
  }, refreshKey)

  // Numbers on the cards: one small "count per status" call.
  useEffect(() => { api(`/dashboard/?scope=${scope}`).then(setStats).catch(() => {}) }, [scope, refreshKey])

  function countFor(c) {
    if (!stats) return undefined
    if (c.overdue) return stats.overdue
    if (!c.statuses) return stats.total
    return c.statuses.reduce((sum, s) => sum + (stats.by_status[s] || 0), 0)
  }

  return (
    <div className="page">
      <section className="stat-grid">
        {config.cards.map((c) => (
          <StatCard key={c.key} icon={c.icon} label={c.label} tone={c.tone} value={countFor(c)}
                    selected={cardKey === c.key} onClick={() => setCardKey(c.key)} />
        ))}
      </section>

      <section className="panel">
        <div className="panel-toolbar">
          <SearchBox value={search} onChange={setSearch}
                     placeholder={showTraveller ? 'Search by code, employee or city…' : 'Search by code or city…'} />
          <label className="select-wrap">
            <ArrowUpDown size={14} />
            <select value={ordering} onChange={(e) => setOrdering(e.target.value)} aria-label="Sort">
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
        </div>

        <Alert>{list.error}</Alert>

        <div className={`table-wrap ${list.loading && list.result ? 'is-loading' : ''}`}>
          <table className="table">
            <thead>
              <tr>
                <th>Request</th>
                {showTraveller && <th>Traveller</th>}
                <th>Trip</th>
                <th>Travel dates</th>
                <th>Status</th>
                <th className="right">Updated</th>
              </tr>
            </thead>
            <tbody>
              {!list.result && list.loading && <SkeletonRows columns={showTraveller ? 6 : 5} />}
              {list.rows.map((r) => (
                <RequestRow key={r.id} request={r} showTraveller={showTraveller} onOpen={onOpen} />
              ))}
            </tbody>
          </table>

          {list.result && list.rows.length === 0 && (
            <EmptyState
              icon={Inbox}
              title={q ? `No results for "${q}"` : cardKey === config.defaultCard ? config.empty : 'No requests in this view'}
              text={q ? 'Try a different code, name or city.' : 'Try another card above to see more.'}
              action={scope === 'mine' && !q && <Button kind="primary" icon={Plus} onClick={onNewRequest}>New request</Button>}
            />
          )}
        </div>

        <Pager {...list} />
      </section>
    </div>
  )
}

function RequestRow({ request: r, showTraveller, onOpen }) {
  const Icon = SERVICE_ICON[r.service]
  return (
    <tr tabIndex={0} onClick={() => onOpen(r.id)} onKeyDown={(e) => e.key === 'Enter' && onOpen(r.id)}>
      <td>
        <div className="cell-main">
          {r.needs_action && <i className="action-dot" title="Waiting on you" />}
          <strong>{r.request_code}</strong>
        </div>
      </td>
      {showTraveller && <td><div className="person"><Avatar name={r.employee_name} size={26} />{r.employee_name}</div></td>}
      <td>
        <div className="trip">
          <span className="trip-icon"><Icon size={15} /></span>
          <div>
            <div className="trip-route">{routeText(r)}</div>
            <div className="subtle xs">{r.service_label}{tripLength(r) && ` · ${tripLength(r)}`}</div>
          </div>
        </div>
      </td>
      <td>{dateRange(r)}</td>
      <td>
        <div className="status-cell">
          <StatusBadge status={r.status} />
          {r.is_overdue && <Badge tone="red" solid>Overdue</Badge>}
        </div>
      </td>
      <td className="right subtle">{timeAgo(r.updated_at)}</td>
    </tr>
  )
}

function SkeletonRows({ columns, rows = 5 }) {
  return [...Array(rows)].map((_, i) => (
    <tr key={i} className="skeleton-row">
      {[...Array(columns)].map((__, j) => <td key={j}><i className="skeleton" /></td>)}
    </tr>
  ))
}
