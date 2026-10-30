// "Account & security" for the signed-in person: change password, own access, recent activity.
import { useEffect, useState } from 'react'
import { BadgeCheck, KeyRound, LogOut, Monitor } from 'lucide-react'
import { api } from '../api.js'
import { EVENT_TONES } from '../constants.js'
import { deviceName, formatDateTime, timeAgo } from '../utils.js'
import Modal from './Modal.jsx'
import PasswordForm from './PasswordForm.jsx'
import { useToast } from './Toast.jsx'
import { Avatar, Badge, Button } from './ui.jsx'

export default function AccountDialog({ user, onClose, onUpdated, onLogout }) {
  const toast = useToast()
  const [activity, setActivity] = useState(null)
  const loadActivity = () => api('/auth/activity/').then(setActivity).catch(() => setActivity([]))
  useEffect(() => { loadActivity() }, [])

  const header = (
    <div className="account-head">
      <Avatar name={user.full_name} size={44} />
      <div>
        <h2>{user.full_name}</h2>
        <p className="subtle">
          {[user.designation, user.department].filter(Boolean).join(' · ') || user.role_label}
          {user.employee_id && ` · ${user.employee_id}`}
        </p>
        <p className="subtle xs">@{user.username}{user.email && ` · ${user.email}`} · signed out after {user.session_minutes / 60}h idle</p>
      </div>
    </div>
  )

  return (
    <Modal header={header} onClose={onClose} size="wide" dismissible bodyClassName="account-grid"
           footer={<Button icon={LogOut} onClick={() => { onClose(); onLogout() }}>Sign out</Button>}>
      <section className="account-section">
        <p className="section-label"><KeyRound size={14} /> Change password</p>
        {user.password_weak && <div className="alert tone-orange">Your current password doesn't meet the policy. Please change it.</div>}
        <PasswordForm onChanged={(u) => {
          onUpdated(u)
          toast('Password changed. Your other devices were signed out.')
          loadActivity()
        }} />
        <p className="subtle xs">Changing your password signs you out on all other devices.</p>
      </section>

      <section className="account-section">
        <p className="section-label"><BadgeCheck size={14} /> Your access</p>
        <p className="access-line">
          <strong>{user.role_label}</strong>
          {user.manager_name && <span className="subtle"> · reports to {user.manager_name}</span>}
        </p>

        <p className="section-label"><Monitor size={14} /> Recent account activity</p>
        {!activity && <p className="subtle">Loading…</p>}
        {activity?.length === 0 && <p className="subtle">No activity yet.</p>}
        <ul className="mini-log">
          {activity?.map((e) => (
            <li key={e.id}>
              <Badge tone={EVENT_TONES[e.type]}>{e.label}</Badge>
              <span className="subtle xs" title={formatDateTime(e.created_at)}>
                {timeAgo(e.created_at)} · {deviceName(e.user_agent)}{e.ip && ` · ${e.ip}`}
              </span>
            </li>
          ))}
        </ul>
        <p className="subtle xs">Don't recognise something? Change your password and tell your administrator.</p>
      </section>
    </Modal>
  )
}
