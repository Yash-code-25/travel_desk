import { useEffect, useState } from 'react'
import { LogOut, Plane } from 'lucide-react'
import { api } from '../api.js'
import ProfileForm from './ProfileForm.jsx'
import { useToast } from './Toast.jsx'
import { Alert, Spinner } from './ui.jsx'

// Shown instead of the app until the person has filled in their travel profile
// (right after they set their own password). The server blocks everything else until then.
export default function ProfileSetup({ user, onDone, onLogout }) {
  const toast = useToast()
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { api('/profile/').then(setProfile).catch((e) => setError(e.message)) }, [])

  async function saved() {
    toast('Profile saved. Welcome to Travel Desk!')
    onDone((await api('/auth/me/')).user)
  }

  return (
    <div className="first-login profile-setup">
      <div className="first-login-card wide">
        <div className="brand">
          <span className="brand-mark"><Plane size={18} /></span>
          <span className="brand-name">Travel Desk</span>
        </div>
        <h1>Complete your profile, {user.full_name.split(' ')[0]}</h1>
        <p className="subtle">
          The Travel Desk uses these details to book your tickets. Fill them in once; you can update them any time
          from <strong>My profile</strong>. Only you, the Travel Desk and administrators can see them. Your manager can't.
        </p>
        <Alert>{error}</Alert>
        {!profile && !error && <div className="center"><Spinner size={22} /></div>}
        {profile && <ProfileForm profile={profile} submitLabel="Save & continue" onSaved={saved} />}
        <button className="link-btn" onClick={onLogout}><LogOut size={14} /> Sign out</button>
      </div>
    </div>
  )
}
