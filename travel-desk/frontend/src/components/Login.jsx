// Sign-in page. Demo accounts come from the server and only exist in demo mode;
// their password never reaches the browser (the server signs them in directly).
import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, Plane, TriangleAlert } from 'lucide-react'
import { api } from '../api.js'
import { Alert, Avatar, Button, Field, Spinner } from './ui.jsx'

export default function Login({ config, onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [capsLock, setCapsLock] = useState(false)
  const [error, setError] = useState('')
  const [failed, setFailed] = useState(false) // at least one wrong attempt: show the lockout rule
  const [lockedFor, setLockedFor] = useState(0) // seconds left while the server has locked sign-in
  const [busy, setBusy] = useState(null) // which sign-in button is working
  const usernameRef = useRef(null)
  const passwordRef = useRef(null)

  // Count down a lockout so the button unlocks by itself when the wait is over.
  useEffect(() => {
    if (lockedFor <= 0) return
    const timer = setTimeout(() => setLockedFor((s) => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [lockedFor])

  async function signIn(path, body, key) {
    setBusy(key)
    setError('')
    try {
      const data = await api(path, { method: 'POST', body })
      onLogin(data.user)
    } catch (err) {
      setError(err.message)
      setFailed(true)
      if (err.status === 429 && err.data.retry_after) setLockedFor(err.data.retry_after)
      setPassword('')
      setBusy(null)
      if (key === 'form') passwordRef.current?.focus()
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!username.trim()) { setError('Enter your username.'); usernameRef.current?.focus(); return }
    if (!password) { setError('Enter your password.'); passwordRef.current?.focus(); return }
    signIn('/auth/login/', { username, password }, 'form')
  }

  const onPasswordKey = (e) => setCapsLock(e.getModifierState?.('CapsLock') ?? false)
  const locked = lockedFor > 0

  return (
    <div className="login">
      <section className="login-hero">
        <div className="brand light">
          <span className="brand-mark"><Plane size={18} /></span>
          <span className="brand-name">Travel Desk</span>
        </div>
        <div>
          <h1>Company travel requests, approvals and tickets.</h1>
          <p>Request a trip, your manager approves it, and the Travel Desk books it.</p>
        </div>
        {/* A boarding pass, just for the look of the page */}
        <div className="pass" aria-hidden="true">
          <div className="pass-main">
            <span className="pass-label">From · To</span>
            <div className="pass-route">PNQ <Plane size={20} /> DEL</div>
            <div className="pass-row">
              <span><span className="pass-label">Traveller</span><strong>YOUR NAME</strong></span>
              <span><span className="pass-label">Status</span><strong>APPROVED</strong></span>
            </div>
          </div>
          <div className="pass-stub">
            <span className="pass-label">Ref</span>
            <strong>TR-0001</strong>
          </div>
        </div>
        <p className="hero-foot">Travel Desk · internal use only</p>
      </section>

      <section className="login-panel">
        <form className="login-form" onSubmit={submit} noValidate>
          {/* The hero (with the logo) is hidden on phones, so the form carries its own brand there */}
          <div className="brand login-brand-mobile">
            <span className="brand-mark"><Plane size={18} /></span>
            <span className="brand-name">Travel Desk</span>
          </div>

          <div className="login-heading">
            <h2>Sign in</h2>
            <p className="subtle">Use your company username and password.</p>
          </div>

          <Field label="Username">
            <input ref={usernameRef} value={username} onChange={(e) => setUsername(e.target.value)} autoFocus
                   autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false}
                   maxLength={150} aria-invalid={Boolean(error) && !username.trim()} />
          </Field>
          <Field label="Password">
            <div className="password-input">
              <input ref={passwordRef} type={showPassword ? 'text' : 'password'} value={password} maxLength={256}
                     onChange={(e) => setPassword(e.target.value)} onKeyDown={onPasswordKey} onKeyUp={onPasswordKey}
                     onBlur={() => setCapsLock(false)} autoComplete="current-password"
                     aria-invalid={Boolean(error) && !password} aria-describedby={capsLock ? 'caps-warning' : undefined} />
              <button type="button" className="icon-btn sm" onClick={() => setShowPassword(!showPassword)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword}>
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {capsLock && <small id="caps-warning" className="caps-warning"><TriangleAlert size={13} /> Caps Lock is on</small>}
          </Field>

          <Alert>{locked ? `Too many failed attempts. Try again in ${formatWait(lockedFor)}.` : error}</Alert>

          <Button kind="primary" type="submit" className="block" loading={busy === 'form'} disabled={Boolean(busy) || locked}>
            {locked ? `Locked · ${formatWait(lockedFor)}` : 'Sign in'}
          </Button>

          <p className="subtle xs center login-help">
            {failed && <>After 5 wrong attempts the account is locked for 15 minutes.<br /></>}
            Forgot your password? Ask your administrator to reset it.
          </p>

          {config.demo_mode && config.demo_users.length > 0 && (
            <>
              <div className="divider"><span>demo mode · one-click accounts</span></div>
              <div className="demo-grid">
                {config.demo_users.map((u) => (
                  <button type="button" key={u.username} className="demo-user" disabled={Boolean(busy) || locked}
                          onClick={() => signIn('/auth/demo-login/', { username: u.username }, u.username)}>
                    {busy === u.username ? <span className="demo-spinner"><Spinner /></span> : <Avatar name={u.name} size={30} />}
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

/** 75 -> "1:15" */
function formatWait(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
