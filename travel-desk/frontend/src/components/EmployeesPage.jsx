// Employees page (administrators): register, edit, reset passwords, unlock, deactivate.
import { useEffect, useState } from 'react'
import {
  BriefcaseBusiness, CircleUser, Gauge, Hourglass, IdCard, KeyRound, LockOpen, LogOut, Pencil,
  ShieldCheck, Ticket, UserCheck, UserPlus, UserX, Users,
} from 'lucide-react'
import { allErrors, api } from '../api.js'
import { ROLE_BY_VALUE } from '../constants.js'
import { useDebounced, usePagedList } from '../hooks.js'
import { formatDateTime, timeAgo } from '../utils.js'
import CredentialsDialog from './CredentialsDialog.jsx'
import EmployeeForm from './EmployeeForm.jsx'
import { ConfirmDialog } from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { ActionMenu, Alert, Avatar, Badge, Banner, Button, EmptyState, FilterTabs, Pager, SearchBox } from './ui.jsx'

// Summary cards, which also filter the list.
const FILTERS = [
  { key: '', label: 'All people', icon: Users, tone: 'slate', count: (u) => u.total },
  { key: 'EMPLOYEE', label: 'Employees', icon: CircleUser, tone: 'indigo', count: (u) => u.employees },
  { key: 'MANAGER', label: 'Managers', icon: BriefcaseBusiness, tone: 'amber', count: (u) => u.managers },
  { key: 'DESK', label: 'Travel Desk', icon: Ticket, tone: 'blue', count: (u) => u.desk },
  { key: 'TRAVEL_MGR', label: 'Travel Managers', icon: Gauge, tone: 'teal', count: (u) => u.travel_managers },
  { key: 'admins', label: 'Administrators', icon: ShieldCheck, tone: 'pink', count: (u) => u.admins },
  { key: 'inactive', label: 'Inactive', icon: UserX, tone: 'gray', count: (u) => u.inactive },
]

export default function EmployeesPage({ me, onPeopleChanged, onViewProfile }) {
  const toast = useToast()
  const [counts, setCounts] = useState(null)
  const [people, setPeople] = useState([]) // everyone, for the "reports to" list
  const [filter, setFilter] = useState('')
  const [search, setSearch] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  const [editing, setEditing] = useState(null) // null | {} (new) | { existing }
  const [credentials, setCredentials] = useState(null) // login details shown once
  const [confirm, setConfirm] = useState(null) // { title, text, confirmLabel, danger, run }
  const [busyId, setBusyId] = useState(null)
  const q = useDebounced(search.trim())
  const list = usePagedList('/security/users/', { q, status: filter }, reloadKey)

  useEffect(() => {
    api('/security/overview/').then((d) => setCounts(d.users)).catch(() => {})
    api('/security/users/?page_size=100').then((d) => setPeople(d.results)).catch(() => {})
  }, [reloadKey])

  const reload = () => { setReloadKey((n) => n + 1); onPeopleChanged() }

  /** Runs an admin action for one person: spinner on their row, toast, reload. */
  async function act(person, request, successMessage) {
    setBusyId(person.id)
    try {
      const out = await request()
      if (successMessage) toast(typeof successMessage === 'function' ? successMessage(out) : successMessage)
      reload()
      return out
    } catch (e) {
      toast(allErrors(e), 'error')
    } finally {
      setBusyId(null)
      setConfirm(null)
    }
  }

  const post = (person, path, body) => () => api(`/security/users/${person.id}/${path}/`, { method: 'POST', body })
  const patch = (person, body) => () => api(`/security/users/${person.id}/`, { method: 'PATCH', body })

  function menuFor(u) {
    const isSelf = u.id === me.id
    return [
      { icon: IdCard, label: 'View profile & documents', onClick: () => onViewProfile(u.id) },
      { icon: Pencil, label: 'Edit details & access', onClick: () => setEditing({ existing: u }) },
      { icon: KeyRound, label: 'Reset password', onClick: () => setConfirm({
        title: `Reset ${u.full_name}'s password?`,
        text: `A new temporary password is created and emailed to ${u.email || 'them'}. They are signed out everywhere and must choose a new password at next sign-in.`,
        confirmLabel: 'Reset password',
        run: async () => {
          const out = await act(u, post(u, 'reset-password', { send_email: true }))
          if (out) setCredentials({ title: 'Password reset', person: u, result: out })
        },
      }) },
      u.locked && { icon: LockOpen, label: 'Unlock account', onClick: () => act(u, post(u, 'unlock'), `${u.full_name} unlocked`) },
      { icon: LogOut, label: 'Sign out everywhere', onClick: () => setConfirm({
        title: `Sign ${u.full_name} out everywhere?`,
        text: isSelf ? 'Your other devices will be signed out. This one stays signed in.' : 'They will need to sign in again on every device.',
        confirmLabel: 'Sign out everywhere',
        run: () => act(u, post(u, 'revoke-sessions'), (r) => `${r.ended} session${r.ended === 1 ? '' : 's'} ended`),
      }) },
      !isSelf && u.is_active && { icon: UserX, label: 'Deactivate', danger: true, onClick: () => setConfirm({
        title: `Deactivate ${u.full_name}?`,
        text: `They are signed out at once and can't sign in. Their history is kept.${u.team_size
          ? ` ${u.team_size} people report to them: their pending approvals move up to ${u.manager_name || 'nobody (assign a new manager first)'}.` : ''}`,
        confirmLabel: 'Deactivate', danger: true,
        run: () => act(u, patch(u, { is_active: false }), (r) => [`${u.full_name} deactivated`, ...(r.work_notes || [])].join(' · ')),
      }) },
      !isSelf && !u.is_active && { icon: UserCheck, label: 'Reactivate', onClick: () => act(u, patch(u, { is_active: true }), `${u.full_name} reactivated`) },
    ].filter(Boolean)
  }

  function onSaved(saved) {
    const wasEdit = Boolean(editing.existing)
    setEditing(null)
    reload()
    if (wasEdit) toast([`${saved.full_name} updated`, ...(saved.work_notes || [])].join(' · '))
    else setCredentials({ title: 'Employee registered', person: saved, result: saved, allowAnother: true })
  }

  return (
    <div className="page">
      <FilterTabs label="Show" value={filter} onChange={setFilter}
                  items={FILTERS.map((f) => ({ key: f.key, label: f.label, count: counts ? f.count(counts) : undefined }))} />

      {counts?.awaiting_first_login > 0 && (
        <Banner tone="blue" icon={Hourglass}
                title={`${counts.awaiting_first_login} ${counts.awaiting_first_login === 1 ? 'person has' : 'people have'} not signed in yet`}>
          They still have a temporary password. If they lost the email, use "Reset password" to send a new one.
        </Banner>
      )}

      <section className="panel">
        <div className="panel-toolbar">
          <SearchBox value={search} onChange={setSearch} placeholder="Search name, username, email, employee ID, department…" />
          <Button kind="primary" icon={UserPlus} onClick={() => setEditing({})}>Register employee</Button>
        </div>
        <Alert>{list.error}</Alert>

        <div className={`table-wrap ${list.loading && list.result ? 'is-loading' : ''}`}>
          <table className="table compact cards">
            <thead>
              <tr><th>Employee</th><th>Position</th><th>Portal role</th><th>Reports to</th><th>Status</th><th>Last sign-in</th><th /></tr>
            </thead>
            <tbody>
              {list.rows.map((u) => (
                <EmployeeRow key={u.id} person={u} isSelf={u.id === me.id} busy={busyId === u.id}
                             menu={menuFor(u)} onOpen={() => setEditing({ existing: u })} />
              ))}
            </tbody>
          </table>
          {list.result && list.rows.length === 0 && (
            <EmptyState icon={Users} title={q ? `Nobody matches "${q}"` : 'No people in this view'}
                        action={<Button kind="primary" icon={UserPlus} onClick={() => setEditing({})}>Register employee</Button>} />
          )}
        </div>
        <Pager {...list} />
        <p className="subtle xs pad-x"><ShieldCheck size={12} /> Every change here is recorded in the security log with your name.</p>
      </section>

      {editing && <EmployeeForm existing={editing.existing} me={me} people={people} onClose={() => setEditing(null)} onSaved={onSaved} />}

      {credentials && (
        <CredentialsDialog title={credentials.title} person={credentials.person} result={credentials.result}
                           onClose={() => setCredentials(null)}
                           onAnother={credentials.allowAnother ? () => { setCredentials(null); setEditing({}) } : null} />
      )}

      {confirm && (
        <ConfirmDialog title={confirm.title} text={confirm.text} confirmLabel={confirm.confirmLabel} danger={confirm.danger}
                       busy={busyId !== null} onConfirm={confirm.run} onCancel={() => setConfirm(null)} />
      )}
    </div>
  )
}

function EmployeeRow({ person: u, isSelf, busy, menu, onOpen }) {
  const role = ROLE_BY_VALUE[u.role]
  return (
    <tr className={u.is_active ? '' : 'muted-row'} tabIndex={0} onClick={onOpen} onKeyDown={(e) => e.key === 'Enter' && onOpen()}>
      <td className="c-first">
        <div className="person">
          <Avatar name={u.full_name} size={32} />
          <div>
            <strong>{u.full_name}</strong>{isSelf && <span className="subtle xs"> (you)</span>}
            <div className="subtle xs">@{u.username}{u.employee_id && ` · ${u.employee_id}`}</div>
          </div>
        </div>
      </td>
      <td data-label="Position">
        <div>{u.designation || <span className="subtle">—</span>}</div>
        <div className="subtle xs">{u.department}</div>
      </td>
      <td data-label="Portal role">
        <Badge tone={role?.tone}>{u.role_label}</Badge>
        {u.team_size > 0 && <div className="subtle xs">{u.team_size} reporting</div>}
      </td>
      <td data-label="Reports to">{u.manager_name || <span className="subtle">—</span>}</td>
      <td className="c-wide">
        <div className="status-cell wrap-badges">
          {u.is_admin && <Badge tone="pink">Admin</Badge>}
          {u.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Inactive</Badge>}
          {u.must_change_password && u.is_active && <Badge tone="blue">Awaiting first sign-in</Badge>}
          {!u.must_change_password && !u.profile_complete && u.is_active && <Badge tone="amber">Profile pending</Badge>}
          {u.locked && <Badge tone="red" solid>Locked</Badge>}
        </div>
      </td>
      <td className="subtle" data-label="Last sign-in" title={u.last_login ? formatDateTime(u.last_login) : ''}>{u.last_login ? timeAgo(u.last_login) : 'Never'}</td>
      <td className="right c-top-right" onClick={(e) => e.stopPropagation()}><ActionMenu items={menu} disabled={busy} /></td>
    </tr>
  )
}
