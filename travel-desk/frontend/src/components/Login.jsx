// Sign-in page. Demo accounts come from the server and only exist in demo mode;
// their password never reaches the browser (the server signs them in directly).
import { useState } from 'react'
import { CircleCheck, Eye, EyeOff, Plane, ShieldCheck, Zap } from 'lucide-react'
import { api } from '../api.js'
import { Alert, Avatar, Button, Field } from './ui.jsx'

export default function Login({ config, onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(null) // which sign-in button is working

  async function signIn(path, body, key) {
    setBusy(key)
    setError('')
    try {
      const data = await api(path, { method: 'POST', body })
      onLogin(data.user)
    } catch (err) {
      setError(err.message)
      setPassword('')
      setBusy(null)
    }
  }

  return (
    <div className="login">
      <section className="login-hero">
        <div className="brand light">
          <span className="brand-mark"><Plane size={18} /></span>
          <span className="brand-name">Travel Desk</span>
        </div>
        <div>
          <h1>Business travel, approved in minutes.</h1>
          <p>Raise a request, get your manager's approval and receive your ticket, all in one place.</p>
          <ul className="hero-points">
            <li><Zap size={18} /> Clear approval steps with live status</li>
            <li><ShieldCheck size={18} /> Account lockout, audit log and session protection</li>
            <li><CircleCheck size={18} /> Tickets and history stored with every trip</li>
          </ul>
        </div>
        <p className="hero-foot">© Travel Desk</p>
      </section>

      <section className="login-panel">
        <form className="login-form" onSubmit={(e) => { e.preventDefault(); signIn('/auth/login/', { username, password }, 'form') }}>
          <h2>Sign in</h2>
          <p className="subtle">Use your company account.</p>

          <Field label="Username">
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" maxLength={150} />
          </Field>
          <Field label="Password">
            <div className="password-input">
              <input type={showPassword ? 'text' : 'password'} value={password} maxLength={256}
                     onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
              <button type="button" className="icon-btn sm" onClick={() => setShowPassword(!showPassword)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}>
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </Field>
          <Alert>{error}</Alert>
          <Button kind="primary" type="submit" className="block" loading={busy === 'form'} disabled={!username || !password || busy}>
            Sign in
          </Button>
          <p className="subtle xs center">After 5 wrong attempts the account is locked for 15 minutes.</p>

          {config.demo_mode && config.demo_users.length > 0 && (
            <>
              <div className="divider"><span>demo mode · one-click accounts</span></div>
              <div className="demo-grid">
                {config.demo_users.map((u) => (
                  <button type="button" key={u.username} className="demo-user" disabled={busy}
                          onClick={() => signIn('/auth/demo-login/', { username: u.username }, u.username)}>
                    <Avatar name={u.name} size={30} />
                    <span><strong>{u.name}</strong><span className="subtle xs">{u.note}</span></span>
                  </button>
                ))}
              </div>
            </>
          )}
        </form>
      </section>
    </div>
  )
}
