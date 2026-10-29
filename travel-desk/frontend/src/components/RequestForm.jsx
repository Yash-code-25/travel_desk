// New travel request, or edit a request that was returned for changes.
import { useState } from 'react'
import { CalendarDays, Info, MapPin, TriangleAlert } from 'lucide-react'
import { api } from '../api.js'
import { SERVICES } from '../constants.js'
import { fieldErrors, todayISO, tripLength } from '../utils.js'
import Modal from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { Alert, Banner, Button, Field } from './ui.jsx'

const MIN_PURPOSE = 10

function initialForm(existing) {
  return {
    service: existing?.service || 'FLIGHT',
    origin: existing?.origin || '',
    destination: existing?.destination || '',
    start_date: existing?.start_date || '',
    end_date: existing?.end_date || '',
    purpose: existing?.purpose || '',
    preferences: existing?.preferences || '',
    estimated_cost: existing?.estimated_cost || '',
  }
}

/** Instant checks in the browser. Django checks everything again (the real rules live there). */
function validate(form) {
  const isHotel = form.service === 'HOTEL'
  const origin = form.origin.trim()
  const destination = form.destination.trim()
  const e = {}
  if (!isHotel && !origin) e.origin = 'Where are you travelling from?'
  if (!destination) e.destination = isHotel ? 'Which city is the hotel in?' : 'Where are you going?'
  if (!isHotel && origin && origin.toLowerCase() === destination.toLowerCase()) e.destination = 'Destination must be different from origin.'
  if (!form.start_date) e.start_date = 'Pick a date.'
  else if (form.start_date < todayISO()) e.start_date = 'Date cannot be in the past.'
  if (isHotel && !form.end_date) e.end_date = 'Pick a check-out date.'
  if (form.end_date && form.start_date && form.end_date < form.start_date) e.end_date = 'Cannot be before the start date.'
  if (isHotel && form.end_date && form.end_date === form.start_date) e.end_date = 'Check-out must be after check-in.'
  if (form.purpose.trim().length < MIN_PURPOSE) e.purpose = `Please write at least ${MIN_PURPOSE} characters.`
  return e
}

export default function RequestForm({ user, existing, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState(() => initialForm(existing))
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const isHotel = form.service === 'HOTEL'
  const noManager = !existing && !user.manager_name

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
    setErrors((e) => ({ ...e, [field]: undefined, non_field_errors: undefined }))
  }

  async function submit(e) {
    e.preventDefault()
    const problems = validate(form)
    if (Object.keys(problems).length) return setErrors(problems)

    const body = {
      ...form,
      origin: isHotel ? '' : form.origin.trim(),
      destination: form.destination.trim(),
      end_date: form.end_date || null, // empty optional fields are sent as null, not ""
      estimated_cost: form.estimated_cost === '' ? null : form.estimated_cost,
    }
    setBusy(true)
    try {
      const saved = existing
        ? await api(`/requests/${existing.id}/`, { method: 'PUT', body })
        : await api('/requests/', { method: 'POST', body })
      toast(`${saved.request_code} sent to ${saved.approver_name} for approval`)
      onSaved(saved)
    } catch (err) {
      setErrors(fieldErrors(err))
    } finally {
      setBusy(false)
    }
  }

  const length = form.start_date && (form.end_date || !isHotel) ? tripLength({ ...form, end_date: form.end_date || null }) : ''

  return (
    <Modal
      title={existing ? `Edit ${existing.request_code}` : 'New travel request'}
      subtitle={existing ? 'Update the details and resubmit for approval.' : user.manager_name && `Goes to ${user.manager_name} for approval.`}
      onClose={onClose}
      onSubmit={submit}
      footer={<>
        <Button type="button" onClick={onClose}>Cancel</Button>
        <Button kind="primary" type="submit" loading={busy} disabled={noManager}>
          {existing ? 'Save & resubmit' : 'Submit for approval'}
        </Button>
      </>}
    >
      {noManager && (
        <Banner tone="orange" icon={TriangleAlert} title="No reporting manager set">
          Your request can't be routed for approval. Ask HR/admin to set your manager.
        </Banner>
      )}
      <Alert>{errors.non_field_errors || errors.detail}</Alert>

      <fieldset className="service-picker">
        <legend>What do you need?</legend>
        {SERVICES.map(({ value, label, icon: Icon }) => (
          <button type="button" key={value} className={`service-option ${form.service === value ? 'selected' : ''}`}
                  onClick={() => set('service', value)} aria-pressed={form.service === value}>
            <Icon size={20} /><span>{label}</span>
          </button>
        ))}
      </fieldset>

      <div className="grid-2">
        {!isHotel && (
          <Field label="From" icon={MapPin} error={errors.origin}>
            <input value={form.origin} onChange={(e) => set('origin', e.target.value)} placeholder="e.g. Pune" />
          </Field>
        )}
        <Field label={isHotel ? 'City' : 'To'} icon={MapPin} error={errors.destination} className={isHotel ? 'span-2' : ''}>
          <input value={form.destination} onChange={(e) => set('destination', e.target.value)} placeholder="e.g. Delhi" />
        </Field>
        <Field label={isHotel ? 'Check-in' : 'Departure'} icon={CalendarDays} error={errors.start_date}>
          <input type="date" min={todayISO()} value={form.start_date} onChange={(e) => set('start_date', e.target.value)} />
        </Field>
        <Field label={isHotel ? 'Check-out' : 'Return'} optional={!isHotel} icon={CalendarDays} error={errors.end_date}>
          <input type="date" min={form.start_date || todayISO()} value={form.end_date || ''} onChange={(e) => set('end_date', e.target.value)} />
        </Field>
      </div>
      {length && <p className="hint"><Info size={14} /> {length}</p>}

      <Field label="Business purpose" error={errors.purpose}>
        <textarea rows={3} value={form.purpose} onChange={(e) => set('purpose', e.target.value)}
                  placeholder="Who are you meeting and why is the trip needed?" />
        {!errors.purpose && (
          <div className="field-foot">
            <small className="subtle">Your approver sees this first.</small>
            <small className={form.purpose.trim().length < MIN_PURPOSE ? 'subtle' : 'ok-text'}>{form.purpose.trim().length}/{MIN_PURPOSE}+</small>
          </div>
        )}
      </Field>

      <div className="grid-2">
        <Field label="Preferences" optional>
          <input value={form.preferences} onChange={(e) => set('preferences', e.target.value)} placeholder="Morning flight, aisle seat…" />
        </Field>
        <Field label="Estimated cost (₹)" optional error={errors.estimated_cost}>
          <input type="number" min="0" step="0.01" value={form.estimated_cost} onChange={(e) => set('estimated_cost', e.target.value)} placeholder="0" />
        </Field>
      </div>
    </Modal>
  )
}
