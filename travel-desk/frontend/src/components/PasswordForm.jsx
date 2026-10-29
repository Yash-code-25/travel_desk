// Change-password form, used in the account dialog and on the first sign-in screen.
import { useState } from 'react'
import { api } from '../api.js'
import { fieldErrors } from '../utils.js'
import { Alert, Button, Field } from './ui.jsx'

const EMPTY = { current_password: '', new_password: '', confirm_password: '' }
const LEVELS = [['Too weak', 'red'], ['Weak', 'red'], ['Fair', 'amber'], ['Good', 'blue'], ['Strong', 'green'], ['Very strong', 'green']]

/** Rough strength guide for the user. The server enforces the real password policy. */
function strength(pw) {
  let score = [pw.length >= 10, pw.length >= 14, /[a-z]/.test(pw) && /[A-Z]/.test(pw), /\d/.test(pw), /[^A-Za-z0-9]/.test(pw)]
    .filter(Boolean).length
  if (pw.length < 10) score = Math.min(score, 1)
  const [label, tone] = LEVELS[score]
  return { label, tone, percent: ((score + 1) / LEVELS.length) * 100 }
}

export default function PasswordForm({ currentLabel = 'Current password', submitLabel = 'Update password', onChanged }) {
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const meter = strength(form.new_password)
  const set = (field, value) => { setForm((f) => ({ ...f, [field]: value })); setErrors({}) }

  async function submit(e) {
    e.preventDefault()
    if (form.new_password !== form.confirm_password) return setErrors({ confirm_password: 'The two new passwords do not match.' })
    setBusy(true)
    try {
      const data = await api('/auth/change-password/', { method: 'POST', body: form })
      setForm(EMPTY)
      onChanged(data.user)
    } catch (err) {
      setErrors(fieldErrors(err))
    } finally {
      setBusy(false)
    }
  }

  const passwordInput = (field, autoComplete) => (
    <input type="password" autoComplete={autoComplete} value={form[field]} onChange={(e) => set(field, e.target.value)} />
  )

  return (
    <form onSubmit={submit} className="password-form" noValidate>
      <Alert>{errors.non_field_errors}</Alert>
      <Field label={currentLabel} error={errors.current_password}>{passwordInput('current_password', 'current-password')}</Field>
      <Field label="New password" error={errors.new_password}
             hint="At least 10 characters. Not a common password, not all numbers, not like your name.">
        {passwordInput('new_password', 'new-password')}
        {form.new_password && (
          <div className={`meter tone-${meter.tone}`}>
            <div className="meter-bar"><i style={{ width: `${meter.percent}%` }} /></div>
            <small>{meter.label}</small>
          </div>
        )}
      </Field>
      <Field label="Confirm new password" error={errors.confirm_password}>{passwordInput('confirm_password', 'new-password')}</Field>
      <Button kind="primary" type="submit" loading={busy}
              disabled={!form.current_password || !form.new_password || !form.confirm_password}>
        {submitLabel}
      </Button>
    </form>
  )
}
