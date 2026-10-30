// Security page (administrators): sign-in numbers and the read-only security log.
import { useEffect, useState } from 'react'
import { Ban, Lock, LogIn, ShieldAlert, ShieldCheck, TriangleAlert, Users } from 'lucide-react'
import { api } from '../api.js'
import { EVENT_TONES } from '../constants.js'
import { useDebounced, usePagedList } from '../hooks.js'
import { deviceName, formatDateTime, timeAgo } from '../utils.js'
import { Alert, Badge, Banner, EmptyState, Pager, SearchBox, StatCard } from './ui.jsx'

const EVENT_FILTERS = [
  ['', 'All events'], ['alerts', 'Alerts only'], ['LOGIN_SUCCESS', 'Signed in'], ['LOGIN_FAILED', 'Failed sign-in'],
  ['LOCKED_OUT', 'Account locked'], ['PERMISSION_DENIED', 'Permission denied'], ['PASSWORD_CHANGED', 'Password changed'],
  ['PASSWORD_RESET', 'Password reset by admin'], ['USER_CREATED', 'User created'], ['USER_UPDATED', 'User updated'],
  ['UPLOAD_REJECTED', 'Upload rejected'],
]

export default function SecurityPage({ onGoToEmployees }) {
  const [overview, setOverview] = useState(null)
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const q = useDebounced(search.trim())
  const list = usePagedList('/security/events/', { q, type })

  useEffect(() => { api('/security/overview/').then(setOverview).catch(() => {}) }, [])

  const day = overview?.last_24h
  const users = overview?.users
  const toggleType = (t) => setType(type === t ? '' : t)
  const locked = overview?.locked_usernames || []

  return (
    <div className="page">
      <section className="stat-grid">
        <StatCard icon={LogIn} label="Sign-ins (24h)" tone="green" value={day?.logins} />
        <StatCard icon={TriangleAlert} label="Failed sign-ins (24h)" tone="amber" value={day?.failed_logins}
                  selected={type === 'LOGIN_FAILED'} onClick={() => toggleType('LOGIN_FAILED')} />
        <StatCard icon={Lock} label="Lockouts (24h)" tone="red" value={day?.lockouts}
                  selected={type === 'LOCKED_OUT'} onClick={() => toggleType('LOCKED_OUT')} />
        <StatCard icon={Ban} label="Blocked actions (24h)" tone="orange" value={day?.denied}
                  selected={type === 'PERMISSION_DENIED'} onClick={() => toggleType('PERMISSION_DENIED')} />
        <StatCard icon={ShieldAlert} label="Locked right now" tone={users?.locked ? 'red' : 'slate'} value={users?.locked} />
        <StatCard icon={Users} label="Active users" tone="indigo" value={users && users.total - users.inactive}
                  hint={users && `${users.inactive} inactive · ${users.admins} admin${users.admins === 1 ? '' : 's'}`} />
      </section>

      {locked.length > 0 && (
        <Banner tone="red" icon={Lock} title={`${locked.length} account${locked.length > 1 ? 's are' : ' is'} locked: ${locked.join(', ')}`}>
          Locks lift by themselves after 15 minutes. To unlock now, go to <button className="link-btn" onClick={onGoToEmployees}>Employees</button>.
        </Banner>
      )}

      <section className="panel">
        <div className="panel-head">
          <ShieldCheck size={18} /><strong>Security log</strong>
          <span className="subtle xs">Every sign-in, lockout, password and access change. Read-only.</span>
        </div>
        <div className="panel-toolbar">
          <SearchBox value={search} onChange={setSearch} placeholder="Search username, IP address or details…" />
          <select className="plain-select" value={type} onChange={(e) => setType(e.target.value)} aria-label="Event type">
            {EVENT_FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <Alert>{list.error}</Alert>

        <div className={`table-wrap ${list.loading && list.result ? 'is-loading' : ''}`}>
          <table className="table compact cards">
            <thead><tr><th>When</th><th>Event</th><th>Account</th><th>IP address</th><th>Device</th><th>Details</th></tr></thead>
            <tbody>
              {list.rows.map((e) => (
                <tr key={e.id} className={`static-row ${e.is_alert ? 'alert-row' : ''}`}>
                  <td className="c-first subtle" title={formatDateTime(e.created_at)}>{timeAgo(e.created_at)}</td>
                  <td className="c-top-right"><Badge tone={EVENT_TONES[e.type]}>{e.label}</Badge></td>
                  <td data-label="Account"><strong>{e.username || '—'}</strong>{e.actor_name && <div className="subtle xs">by {e.actor_name}</div>}</td>
                  <td className="mono" data-label="IP address">{e.ip || '—'}</td>
                  <td className="subtle c-wide" data-label="Device">{e.user_agent ? deviceName(e.user_agent) : '—'}</td>
                  <td className="wrap c-wide">{e.detail || <span className="subtle">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.result && list.rows.length === 0 && <EmptyState icon={ShieldCheck} title="No events match" />}
        </div>
        <Pager {...list} />
      </section>
    </div>
  )
}
