import { KeyRound, LogOut, Plane } from 'lucide-react'
import PasswordForm from './PasswordForm.jsx'
import { useToast } from './Toast.jsx'

// Shown instead of the app when someone signs in with a temporary password
// (new account or admin reset). The server blocks everything else until this is done.
export default function FirstLogin({ user, onDone, onLogout }) {
  const toast = useToast()
  return (
    <div className="first-login">
      <div className="first-login-card">
        <div className="brand">
          <span className="brand-mark"><Plane size={18} /></span>
          <span className="brand-name">Travel Desk</span>
        </div>
        <div className="first-login-icon"><KeyRound size={22} /></div>
        <h1>Welcome, {user.full_name.split(' ')[0]}!</h1>
        <p className="subtle">
          You signed in with a temporary password. Choose your own password to continue.
          Only you should know it.
        </p>
        <PasswordForm
          currentLabel="Temporary password (from your email)"
          submitLabel="Set my password & continue"
          onChanged={(u) => { toast('Password set. Welcome to Travel Desk!'); onDone(u) }}
        />
        <button className="link-btn" onClick={onLogout}><LogOut size={14} /> Sign out</button>
      </div>
    </div>
  )
}
