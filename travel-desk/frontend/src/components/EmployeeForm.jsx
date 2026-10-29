// Register a new employee (no `existing`) or edit one. Administrators only.
import { useEffect, useState } from 'react'
import { AtSign, BriefcaseBusiness, Mail, Phone, ShieldCheck, TriangleAlert, User } from 'lucide-react'
import { api } from '../api.js'
import { ROLES } from '../constants.js'
import { useDebounced } from '../hooks.js'
import { fieldErrors } from '../utils.js'
import Modal from './Modal.jsx'
import { Alert, Banner, Button, Field, Toggle } from './ui.jsx'

const BLANK = {
  first_name: '', last_name: '', email: '', phone: '',
  employee_id: '', department: '', designation: '',
  role: 'EMPLOYEE', manager_id: '', is_admin: false, is_active: true,
  username: '', send_email: true,
}

function validate(form) {
  const e = {}
  if (!form.first_name.trim()) e.first_name = 'Required.'
  if (!form.last_name.trim()) e.last_name = 'Required.'
  if (!/^\S+@\S+\.\S+$/.test(form.email.trim())) e.email = 'Enter a valid email address.'
  if (form.phone && !/^\+?[0-9 ()-]{7,20}$/.test(form.phone.trim())) e.phone = 'Enter a valid phone number.'
  return e
}

export default function EmployeeForm({ existing, me, people, onClose, onSaved }) {
  const editing = Boolean(existing)
  const isSelf = editing && existing.id === me.id
  const [form, setForm] = useState(() => editing ? { ...BLANK, ...existing, manager_id: existing.manager_id ?? '' } : BLANK)
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [usernameEdited, setUsernameEdited] = useState(false)

  const set = (field, value) => {
    setForm((f) => ({ ...f, [field]: value }))
    setErrors((e) => ({ ...e, [field]: undefined, non_field_errors: undefined }))
  }

  // While registering, suggest a free username from the name (asha.patil, asha.patil2 ...).
  const nameKey = useDebounced(`${form.first_name}|${form.last_name}`, 350)
  useEffect(() => {
    if (editing || usernameEdited) return
    const [first, last] = nameKey.split('|')
    if (!first.trim() && !last.trim()) return
    const query = new URLSearchParams({ first, last })
    api(`/security/users/suggest-username/?${query}`).then((d) => set('username', d.username)).catch(() => {})
  }, [nameKey, editing, usernameEdited])

  async function submit(ev) {
    ev.preventDefault()
    const problems = validate(form)
    if (Object.keys(problems).length) return setErrors(problems)

    const body = {
      first_name: form.first_name, last_name: form.last_name, email: form.email, phone: form.phone,
      employee_id: form.employee_id, department: form.department, designation: form.designation,
      role: form.role, manager_id: form.manager_id === '' ? null : Number(form.manager_id), is_admin: form.is_admin,
      ...(editing ? { is_active: form.is_active } : { username: form.username, send_email: form.send_email }),
    }
    setBusy(true)
    try {
      onSaved(editing
        ? await api(`/security/users/${existing.id}/`, { method: 'PATCH', body })
        : await api('/security/users/', { method: 'POST', body }))
    } catch (err) {
      setErrors(fieldErrors(err))
    } finally {
      setBusy(false)
    }
  }

  const managers = people.filter((p) => p.is_active && p.id !== existing?.id)
  const newManager = editing && form.manager_id && String(form.manager_id) !== String(existing.manager_id ?? '')
    && managers.find((m) => String(m.id) === String(form.manager_id))

  return (
    <Modal
      title={editing ? `Edit ${existing.full_name}` : 'Register employee'}
      subtitle={editing ? 'Changes apply immediately and are recorded in the security log.'
        : 'They get a username and a temporary password, and must set their own password at first sign-in.'}
      size="wide" onClose={onClose} onSubmit={submit}
      footer={<>
        <Button type="button" onClick={onClose}>Cancel</Button>
        <Button kind="primary" type="submit" loading={busy}>{editing ? 'Save changes' : 'Register & create login'}</Button>
      </>}
    >
      <Alert>{errors.non_field_errors}</Alert>

      <fieldset className="form-section">
        <legend><User size={15} /> Personal details</legend>
        <div className="grid-2">
          <Field label="First name" error={errors.first_name}>
            <input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} maxLength={150} autoFocus />
          </Field>
          <Field label="Last name" error={errors.last_name}>
            <input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} maxLength={150} />
          </Field>
          <Field label="Work email" icon={Mail} error={errors.email}>
            <input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} placeholder="name@company.in" maxLength={254} />
          </Field>
          <Field label="Phone" optional icon={Phone} error={errors.phone}>
            <input value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="+91 98765 43210" maxLength={20} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="form-section">
        <legend><BriefcaseBusiness size={15} /> Job</legend>
        <div className="grid-3">
          <Field label="Employee ID" optional error={errors.employee_id}>
            <input value={form.employee_id} onChange={(e) => set('employee_id', e.target.value)} placeholder="EMP-1024" maxLength={30} />
          </Field>
          <Field label="Department" error={errors.department}>
            <input value={form.department} onChange={(e) => set('department', e.target.value)} placeholder="Sales" maxLength={100} />
          </Field>
          <Field label="Designation (job title)" error={errors.designation}>
            <input value={form.designation} onChange={(e) => set('designation', e.target.value)} placeholder="Senior Sales Executive" maxLength={100} />
          </Field>
        </div>
      </fieldset>

      <fieldset className="form-section">
        <legend><ShieldCheck size={15} /> Portal access</legend>
        <div className="role-picker">
          {ROLES.map((r) => (
            <button type="button" key={r.value} className={`role-option ${form.role === r.value ? 'selected' : ''}`}
                    onClick={() => set('role', r.value)} aria-pressed={form.role === r.value}>
              <strong>{r.label}</strong>
              <span>{r.can}</span>
            </button>
          ))}
        </div>

        <div className="grid-2">
          <Field label="Reports to (approves their travel)" error={errors.manager_id}
                 hint={newManager ? `Their pending requests will move to ${newManager.full_name}.`
                   : !form.manager_id && form.role !== 'MANAGER' && !form.is_admin ? "Without a manager they can't submit travel requests." : ''}>
            <select className="field-select" value={form.manager_id} onChange={(e) => set('manager_id', e.target.value)}>
              <option value="">— No manager —</option>
              {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name}{m.designation && ` — ${m.designation}`}</option>)}
            </select>
          </Field>

          <div className="field">
            <span>Extra rights</span>
            <Toggle checked={form.is_admin} disabled={isSelf} onChange={(v) => set('is_admin', v)}
                    title="Administrator" text="Can register people, change access and see the security log." />
            {errors.is_admin && <small className="field-error">{errors.is_admin}</small>}
            {editing && (
              <Toggle checked={form.is_active} disabled={isSelf} onChange={(v) => set('is_active', v)}
                      title="Account active" text="Turn off to block sign-in (history is kept)." />
            )}
            {errors.is_active && <small className="field-error">{errors.is_active}</small>}
          </div>
        </div>

        {form.is_admin && !existing?.is_admin && (
          <Banner tone="orange" icon={TriangleAlert} title="Administrator access is powerful">
            Only give it to people who manage the portal.
          </Banner>
        )}
      </fieldset>

      <fieldset className="form-section">
        <legend><AtSign size={15} /> Sign-in</legend>
        <div className="grid-2">
          <Field label="Username" error={errors.username}
                 hint={editing ? 'Usernames cannot be changed.' : 'Suggested from the name. You can change it.'}>
            <input value={form.username} disabled={editing} maxLength={150}
                   onChange={(e) => { setUsernameEdited(true); set('username', e.target.value) }} />
          </Field>
          {!editing && (
            <div className="field">
              <span>Login details</span>
              <Toggle checked={form.send_email} onChange={(v) => set('send_email', v)}
                      title="Email username & temporary password"
                      text={`Sent to ${form.email || 'their work email'}. You'll also see it once on screen.`} />
            </div>
          )}
        </div>
      </fieldset>
    </Modal>
  )
}
