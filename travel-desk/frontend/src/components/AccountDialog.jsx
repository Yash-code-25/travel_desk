// "My profile" for the signed-in person: travel profile (view / edit), change password, own access, recent activity.
import { useEffect, useState } from 'react'
import { BadgeCheck, KeyRound, LogOut, Monitor, Pencil, ShieldCheck, UserRound } from 'lucide-react'
import { api } from '../api.js'
import { EVENT_TONES } from '../constants.js'
import { deviceName, formatDateTime, timeAgo } from '../utils.js'
import Modal from './Modal.jsx'
import PasswordForm from './PasswordForm.jsx'
import ProfileForm from './ProfileForm.jsx'
import ProfileView from './ProfileView.jsx'
import { useToast } from './Toast.jsx'
import { Alert, Avatar, Badge, Button, Spinner } from './ui.jsx'

export default function AccountDialog({ user, initialTab = 'profile', onClose, onUpdated, onLogout }) {
  const toast = useToast()
  const [tab, setTab] = useState(initialTab)
  const [profile, setProfile] = useState(null)
  const [profileError, setProfileError] = useState('')
  const [editing, setEditing] = useState(false)
  const [activity, setActivity] = useState(null)
  const loadActivity = () => api('/auth/activity/').then(setActivity).catch(() => setActivity([]))
  useEffect(() => { loadActivity() }, [])
  useEffect(() => { api('/profile/').then(setProfile).catch((e) => setProfileError(e.message)) }, [])

  async function profileSaved(saved) {
    setProfile(saved)
    setEditing(false)
    toast('Profile updated')
    const me = await api('/auth/me/').catch(() => null)
    if (me?.user) onUpdated(me.user) // name, designation etc. shown elsewhere
  }

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
    <Modal header={header} onClose={onClose} size="wide" dismissible={!editing}
           footer={!editing && <Button icon={LogOut} onClick={() => { onClose(); onLogout() }}>Sign out</Button>}>
      <div className="panel-tabs modal-tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'profile'} className={tab === 'profile' ? 'active' : ''} onClick={() => setTab('profile')}>
          <UserRound size={15} /> My profile
        </button>
        <button role="tab" aria-selected={tab === 'security'} className={tab === 'security' ? 'active' : ''}
                onClick={() => { setTab('security'); setEditing(false) }}>
          <ShieldCheck size={15} /> Password & security
        </button>
      </div>

      {tab === 'profile' && (
        <div className="account-profile">
          <Alert>{profileError}</Alert>
          {!profile && !profileError && <div className="center"><Spinner size={22} /></div>}
          {profile && !editing && (
            <>
              <div className="profile-toolbar">
                <p className="subtle xs">Visible only to you, the Travel Desk and administrators. Your manager can't see it.</p>
                <Button icon={Pencil} onClick={() => setEditing(true)}>Edit profile</Button>
              </div>
              <ProfileView profile={profile} />
            </>
          )}
          {profile && editing && (
            <ProfileForm profile={profile} onSaved={profileSaved} onCancel={() => setEditing(false)} />
          )}
        </div>
      )}

      {tab === 'security' && (
        <div className="account-grid">
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
        </div>
      )}
    </Modal>
  )
}
