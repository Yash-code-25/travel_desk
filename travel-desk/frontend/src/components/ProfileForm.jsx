// Travel profile form: basic information, identity documents, passport & visas, travel preferences.
// Shown after the first sign-in (must be filled before the app opens) and from "My profile" to edit.
import { useState } from 'react'
import { BookUser, CreditCard, FileText, IdCard, Plane, Plus, Trash2, Upload, User } from 'lucide-react'
import { api } from '../api.js'
import { COUNTRIES, GENDERS, MEALS, SEATS } from '../constants.js'
import { Alert, Button, Field, Toggle } from './ui.jsx'

const MAX_MB = 5
const FILE_TYPES = ['pdf', 'png', 'jpg', 'jpeg']
const PHONE = /^\+?[0-9 ()-]{7,20}$/
const LAST4 = /^[0-9]{4}$/
const today = () => new Date().toISOString().slice(0, 10)
let nextKey = 1 // local keys for visa / frequent-flyer rows

function fromProfile(p) {
  const v = (x) => x ?? ''
  return {
    first_name: v(p.first_name), last_name: v(p.last_name), phone: v(p.phone),
    designation: v(p.designation), department: v(p.department), date_of_birth: v(p.date_of_birth),
    gender: v(p.gender), address: v(p.address),
    emergency_contact_name: v(p.emergency_contact_name), emergency_contact_phone: v(p.emergency_contact_phone),
    aadhaar_last4: v(p.aadhaar_last4), pan_number: v(p.pan_number),
    has_passport: Boolean(p.has_passport), passport_number: v(p.passport_number),
    passport_place_of_issue: v(p.passport_place_of_issue), passport_issue_date: v(p.passport_issue_date),
    passport_expiry_date: v(p.passport_expiry_date),
    visas: (p.visas || []).map((x) => ({ ...x, key: nextKey++, upload: null })),
    seat_preference: v(p.seat_preference), meal_preference: v(p.meal_preference),
    has_frequent_flyer: Boolean(p.has_frequent_flyer),
    frequent_flyers: (p.frequent_flyers || []).map((x) => ({ ...x, key: nextKey++ })),
    has_forex_card: Boolean(p.has_forex_card), forex_bank: v(p.forex_bank), forex_card_last4: v(p.forex_card_last4),
    aadhaar_upload: null, pan_upload: null, passport_upload: null,
  }
}

function fileProblem(file) {
  if (!file) return ''
  if (!FILE_TYPES.includes(file.name.split('.').pop().toLowerCase())) return 'Only PDF, PNG or JPG files.'
  if (file.size > MAX_MB * 1024 * 1024) return `Larger than ${MAX_MB} MB.`
  return ''
}

/** Instant checks (the server checks everything again). Returns {field: message}. */
function validate(f, p) {
  const e = {}
  const need = (field, msg = 'Required.') => { if (!String(f[field]).trim()) e[field] = msg }
  ;['first_name', 'last_name', 'designation', 'department', 'gender', 'emergency_contact_name',
    'seat_preference', 'meal_preference'].forEach((k) => need(k))
  need('date_of_birth', 'Enter your date of birth.')
  if (f.address.trim().length < 10) e.address = 'Enter your full address.'
  if (!PHONE.test(f.phone.trim())) e.phone = 'Enter a valid phone number.'
  if (!PHONE.test(f.emergency_contact_phone.trim())) e.emergency_contact_phone = 'Enter a valid phone number.'
  if (!LAST4.test(f.aadhaar_last4)) e.aadhaar_last4 = 'Enter the last 4 digits.'
  if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(f.pan_number.trim().toUpperCase())) e.pan_number = 'Enter a valid PAN, e.g. ABCDE1234F.'
  if (!f.aadhaar_upload && !p.aadhaar_file) e.aadhaar_file = 'Upload your masked Aadhaar.'
  if (!f.pan_upload && !p.pan_file) e.pan_file = 'Upload your PAN card.'
  if (f.has_passport) {
    if (!/^[A-Z0-9]{6,9}$/.test(f.passport_number.trim().toUpperCase())) e.passport_number = 'Enter the passport number.'
    need('passport_place_of_issue')
    need('passport_issue_date')
    if (!f.passport_expiry_date) e.passport_expiry_date = 'Required.'
    else if (f.passport_expiry_date <= today()) e.passport_expiry_date = 'This passport has expired.'
    if (!f.passport_upload && !p.passport_file) e.passport_file = 'Upload your passport.'
  }
  if (f.has_frequent_flyer && !f.frequent_flyers.some((x) => x.airline.trim() && x.membership_number.trim())) {
    e.frequent_flyers = 'Add your airline and membership number.'
  }
  if (f.has_forex_card) {
    need('forex_bank')
    if (!LAST4.test(f.forex_card_last4)) e.forex_card_last4 = 'Enter the last 4 digits.'
  }
  ;[['aadhaar_upload', 'aadhaar_file'], ['pan_upload', 'pan_file'], ['passport_upload', 'passport_file']].forEach(([u, k]) => {
    if (fileProblem(f[u])) e[k] = fileProblem(f[u])
  })
  return e
}

/** Server errors -> {field: message}; visa / frequent-flyer rows come back as lists. */
function serverErrors(err) {
  if (err.status !== 400) return { non_field_errors: err.message }
  const out = {}
  for (const [k, v] of Object.entries(err.data)) {
    if (k === 'visas' && Array.isArray(v) && typeof v[0] === 'object') {
      v.forEach((row, i) => Object.entries(row || {}).forEach(([f, m]) => { out[`visa_${i}_${f}`] = [].concat(m).join(' ') }))
    } else if (k === 'frequent_flyers' && Array.isArray(v) && typeof v[0] === 'object') {
      out.frequent_flyers = v.flatMap((row) => Object.values(row || {}).flat()).join(' ')
    } else {
      out[k] = [].concat(v).join(' ')
    }
  }
  return out
}

export default function ProfileForm({ profile, submitLabel = 'Save profile', onSaved, onCancel }) {
  const [form, setForm] = useState(() => fromProfile(profile))
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)

  const set = (field, value) => {
    setForm((f) => ({ ...f, [field]: value }))
    setErrors((e) => ({ ...e, [field]: undefined, non_field_errors: undefined }))
  }
  const clear = (field) => setErrors((e) => ({ ...e, [field]: undefined }))
  const setRow = (list, key, field, value) =>
    setForm((f) => ({ ...f, [list]: f[list].map((r) => (r.key === key ? { ...r, [field]: value } : r)) }))
  const addRow = (list, row) => setForm((f) => ({ ...f, [list]: [...f[list], { ...row, key: nextKey++ }] }))
  const removeRow = (list, key) => setForm((f) => ({ ...f, [list]: f[list].filter((r) => r.key !== key) }))
  const input = (field, props = {}) => (
    <input value={form[field]} onChange={(e) => set(field, e.target.value)} aria-invalid={Boolean(errors[field])} {...props} />
  )

  async function submit(ev) {
    ev.preventDefault()
    const visas = form.has_passport ? form.visas : []
    const problems = validate(form, profile)
    visas.forEach((v, i) => {
      if (!v.country.trim()) problems[`visa_${i}_country`] = 'Required.'
      if (!v.visa_type.trim()) problems[`visa_${i}_visa_type`] = 'Required.'
      if (!v.expiry_date) problems[`visa_${i}_expiry_date`] = 'Required.'
      else if (v.expiry_date < today()) problems[`visa_${i}_expiry_date`] = 'Expired: remove it.'
      if (!v.upload && !v.file) problems[`visa_${i}_file`] = 'Upload a copy.'
      else if (fileProblem(v.upload)) problems[`visa_${i}_file`] = fileProblem(v.upload)
    })
    if (Object.keys(problems).length) {
      setErrors({ ...problems, non_field_errors: 'Some details are missing or wrong. Check the fields marked in red.' })
      return
    }

    const { aadhaar_upload, pan_upload, passport_upload, ...rest } = form
    const data = {
      ...rest,
      visas: visas.map(({ id, country, visa_type, expiry_date }) => ({ id, country, visa_type, expiry_date })),
      frequent_flyers: form.has_frequent_flyer
        ? form.frequent_flyers.filter((x) => x.airline.trim() || x.membership_number.trim())
          .map(({ airline, membership_number }) => ({ airline, membership_number }))
        : [],
    }
    const body = new FormData()
    body.append('data', JSON.stringify(data))
    if (aadhaar_upload) body.append('aadhaar_file', aadhaar_upload)
    if (pan_upload) body.append('pan_file', pan_upload)
    if (passport_upload && form.has_passport) body.append('passport_file', passport_upload)
    visas.forEach((v, i) => v.upload && body.append(`visa_file_${i}`, v.upload))

    setBusy(true)
    try {
      onSaved(await api('/profile/', { method: 'PUT', body }))
    } catch (err) {
      const errs = serverErrors(err)
      setErrors({ ...errs, non_field_errors: errs.non_field_errors || 'Some details need fixing. Check the fields marked in red.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="profile-form" onSubmit={submit} noValidate>
      <fieldset className="form-section">
        <legend><User size={15} /> Basic information</legend>
        <p className="subtle xs">
          @{profile.username}{profile.email && ` · ${profile.email}`}{profile.employee_id && ` · Employee ID ${profile.employee_id}`}
          {' '}(set by your administrator)
        </p>
        <div className="grid-2">
          <Field label="First name" error={errors.first_name} hint="Exactly as on your ID: tickets are booked in this name.">
            {input('first_name', { maxLength: 150, autoComplete: 'given-name' })}
          </Field>
          <Field label="Last name" error={errors.last_name}>{input('last_name', { maxLength: 150, autoComplete: 'family-name' })}</Field>
          <Field label="Date of birth" error={errors.date_of_birth}>{input('date_of_birth', { type: 'date', max: today() })}</Field>
          <Field label="Gender" error={errors.gender}>
            <select className="field-select" value={form.gender} onChange={(e) => set('gender', e.target.value)}>
              <option value="">Select…</option>
              {GENDERS.map((g) => <option key={g.value} value={g.value}>{g.label}</option>)}
            </select>
          </Field>
          <Field label="Mobile number" error={errors.phone}>
            {input('phone', { maxLength: 20, placeholder: '+91 98765 43210', inputMode: 'tel', autoComplete: 'tel' })}
          </Field>
          <Field label="Department" error={errors.department}>{input('department', { maxLength: 100, placeholder: 'Sales' })}</Field>
          <Field label="Designation (job title)" error={errors.designation} className="span-2">
            {input('designation', { maxLength: 100, placeholder: 'Senior Sales Executive' })}
          </Field>
          <Field label="Address" error={errors.address} className="span-2">
            <textarea rows={2} value={form.address} maxLength={500} onChange={(e) => set('address', e.target.value)}
                      aria-invalid={Boolean(errors.address)} autoComplete="street-address" />
          </Field>
          <Field label="Emergency contact name" error={errors.emergency_contact_name}>{input('emergency_contact_name', { maxLength: 150 })}</Field>
          <Field label="Emergency contact phone" error={errors.emergency_contact_phone}>
            {input('emergency_contact_phone', { maxLength: 20, placeholder: '+91 91234 56789', inputMode: 'tel' })}
          </Field>
        </div>
      </fieldset>

      <fieldset className="form-section">
        <legend><IdCard size={15} /> Identity documents</legend>
        <div className="grid-2">
          <Field label="Aadhaar: last 4 digits" error={errors.aadhaar_last4} hint="Only the last 4 digits are stored.">
            {input('aadhaar_last4', { maxLength: 4, inputMode: 'numeric', placeholder: '1234' })}
          </Field>
          <DocumentInput label="Masked Aadhaar copy" current={profile.aadhaar_file} file={form.aadhaar_upload}
                         error={errors.aadhaar_file} onChange={(f) => { set('aadhaar_upload', f); clear('aadhaar_file') }} />
          <Field label="PAN number" error={errors.pan_number}>
            {input('pan_number', { maxLength: 10, placeholder: 'ABCDE1234F', className: 'upper' })}
          </Field>
          <DocumentInput label="PAN card copy" current={profile.pan_file} file={form.pan_upload}
                         error={errors.pan_file} onChange={(f) => { set('pan_upload', f); clear('pan_file') }} />
        </div>
      </fieldset>

      <fieldset className="form-section">
        <legend><BookUser size={15} /> Passport & visas</legend>
        <Toggle checked={form.has_passport} onChange={(v) => set('has_passport', v)}
                title="I have a passport" text="Needed for international travel. Leave off if you don't have one." />
        {form.has_passport && (
          <>
            <div className="grid-2">
              <Field label="Passport number" error={errors.passport_number}>
                {input('passport_number', { maxLength: 9, placeholder: 'Z1234567', className: 'upper' })}
              </Field>
              <Field label="Place of issue" error={errors.passport_place_of_issue}>{input('passport_place_of_issue', { maxLength: 100 })}</Field>
              <Field label="Date of issue" error={errors.passport_issue_date}>{input('passport_issue_date', { type: 'date', max: today() })}</Field>
              <Field label="Expiry date" error={errors.passport_expiry_date}>{input('passport_expiry_date', { type: 'date' })}</Field>
            </div>
            <DocumentInput label="Passport copy (front & back pages)" current={profile.passport_file} file={form.passport_upload}
                           error={errors.passport_file} onChange={(f) => { set('passport_upload', f); clear('passport_file') }} />

            <div className="field">
              <span>Valid visas <em>optional</em></span>
              {form.visas.map((v, i) => (
                <div className="list-row" key={v.key}>
                  <div className="grid-3">
                    <Field label="Country" error={errors[`visa_${i}_country`]}>
                      <select className="field-select" value={v.country} onChange={(e) => setRow('visas', v.key, 'country', e.target.value)}>
                        <option value="">Select…</option>
                        {COUNTRIES.filter((c) => c !== 'India').map((c) => <option key={c}>{c}</option>)}
                      </select>
                    </Field>
                    <Field label="Visa type" error={errors[`visa_${i}_visa_type`]}>
                      <input value={v.visa_type} maxLength={100} placeholder="Business, B1/B2…" onChange={(e) => setRow('visas', v.key, 'visa_type', e.target.value)} />
                    </Field>
                    <Field label="Valid until" error={errors[`visa_${i}_expiry_date`]}>
                      <input type="date" value={v.expiry_date} min={today()} onChange={(e) => setRow('visas', v.key, 'expiry_date', e.target.value)} />
                    </Field>
                  </div>
                  <DocumentInput label="Visa copy" current={v.file} file={v.upload} error={errors[`visa_${i}_file`]}
                                 onChange={(f) => setRow('visas', v.key, 'upload', f)} />
                  <button type="button" className="link-btn danger-link" onClick={() => removeRow('visas', v.key)}>
                    <Trash2 size={14} /> Remove visa
                  </button>
                </div>
              ))}
              <Button type="button" icon={Plus} className="self-start"
                      onClick={() => addRow('visas', { country: '', visa_type: '', expiry_date: '', upload: null })}>
                Add a visa
              </Button>
            </div>
          </>
        )}
      </fieldset>

      <fieldset className="form-section">
        <legend><Plane size={15} /> Travel preferences</legend>
        <div className="grid-2">
          <Field label="Seat preference" error={errors.seat_preference}>
            <select className="field-select" value={form.seat_preference} onChange={(e) => set('seat_preference', e.target.value)}>
              <option value="">Select…</option>
              {SEATS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </Field>
          <Field label="Meal preference" error={errors.meal_preference}>
            <select className="field-select" value={form.meal_preference} onChange={(e) => set('meal_preference', e.target.value)}>
              <option value="">Select…</option>
              {MEALS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </Field>
        </div>

        <Toggle checked={form.has_frequent_flyer} title="I have a frequent flyer membership" text="Miles are added when the desk books your flights."
                onChange={(on) => {
                  set('has_frequent_flyer', on)
                  if (on && !form.frequent_flyers.length) addRow('frequent_flyers', { airline: '', membership_number: '' })
                }} />
        {form.has_frequent_flyer && (
          <div className="field">
            {form.frequent_flyers.map((x) => (
              <div className="inline-row" key={x.key}>
                <Field label="Airline"><input value={x.airline} maxLength={100} placeholder="Air India" onChange={(e) => setRow('frequent_flyers', x.key, 'airline', e.target.value)} /></Field>
                <Field label="Membership number">
                  <input value={x.membership_number} maxLength={30} className="upper" onChange={(e) => setRow('frequent_flyers', x.key, 'membership_number', e.target.value)} />
                </Field>
                <button type="button" className="icon-btn bordered" aria-label="Remove membership" onClick={() => removeRow('frequent_flyers', x.key)}>
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
            {errors.frequent_flyers && <small className="field-error">{errors.frequent_flyers}</small>}
            <Button type="button" icon={Plus} className="self-start" onClick={() => addRow('frequent_flyers', { airline: '', membership_number: '' })}>
              Add another airline
            </Button>
          </div>
        )}

        <Toggle checked={form.has_forex_card} onChange={(v) => set('has_forex_card', v)}
                title="I have a forex card" text="For trips abroad. Only the bank and last 4 digits are stored." />
        {form.has_forex_card && (
          <div className="grid-2">
            <Field label="Issuing bank" error={errors.forex_bank}>{input('forex_bank', { maxLength: 100, placeholder: 'HDFC Bank' })}</Field>
            <Field label="Card: last 4 digits" error={errors.forex_card_last4} icon={CreditCard}>
              {input('forex_card_last4', { maxLength: 4, inputMode: 'numeric', placeholder: '4321' })}
            </Field>
          </div>
        )}
      </fieldset>

      <Alert>{errors.non_field_errors}</Alert>
      <div className="form-actions">
        {onCancel && <Button type="button" onClick={onCancel} disabled={busy}>Cancel</Button>}
        <Button kind="primary" type="submit" loading={busy}>{submitLabel}</Button>
      </div>
    </form>
  )
}

/** File picker for one document. Shows the stored copy (if any) and the newly chosen file. */
function DocumentInput({ label, current, file, error, onChange }) {
  return (
    <div className="field">
      <span>{label}</span>
      <label className={`dropzone sm ${file ? 'has-file' : ''} ${error ? 'invalid' : ''}`}>
        <input type="file" hidden accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => onChange(e.target.files[0] || null)} />
        {file ? <FileText size={18} /> : <Upload size={18} />}
        <span>
          {file ? <><strong>{file.name}</strong> <span className="subtle xs">· click to change</span></>
            : current ? <><strong>Uploaded</strong> <span className="subtle xs">· click to replace</span></>
              : <><strong>Choose file</strong> <span className="subtle xs">· PDF, PNG or JPG, max {MAX_MB} MB</span></>}
        </span>
      </label>
      {current && !file && <a className="link-btn self-start" href={current}><FileText size={13} /> Download current copy</a>}
      {error && <small className="field-error">{error}</small>}
    </div>
  )
}
