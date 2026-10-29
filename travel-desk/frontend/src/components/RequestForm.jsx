// New travel request (one trip, many bookings), or edit a request that was returned for changes.
import { useState } from 'react'
import {
  ArrowDown, ArrowUp, CalendarDays, Info, Mail, MapPin, Phone, Plus, Trash2, TriangleAlert, Undo2, User, Users,
} from 'lucide-react'
import { api } from '../api.js'
import { SERVICES } from '../constants.js'
import { fieldErrors, todayISO, tripLength } from '../utils.js'
import Modal from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { Alert, Banner, Button, Field } from './ui.jsx'

const MIN_PURPOSE = 10
const MAX_LEGS = 10
let nextKey = 1 // stable React keys for legs

function newLeg(fields) {
  return { key: nextKey++, service: 'FLIGHT', origin: '', destination: '', date: '', end_date: '', notes: '', is_return: false, ...fields }
}

function initialForm(existing) {
  const other = existing && !existing.traveller_is_requester
  return {
    traveller_is_requester: existing ? existing.traveller_is_requester : true,
    traveller_name: other ? existing.traveller_name : '',
    traveller_phone: other ? existing.traveller_phone : '',
    traveller_email: other ? existing.traveller_email : '',
    legs: existing ? existing.legs.map((l) => newLeg({ ...l, end_date: l.end_date || '' })) : [newLeg()],
    purpose: existing?.purpose || '',
    preferences: existing?.preferences || '',
    estimated_cost: existing?.estimated_cost || '',
  }
}

/** The day you're free for the next booking: the travel date, or the hotel check-out. */
const freeFrom = (leg) => (leg.service === 'HOTEL' && leg.end_date) || leg.date

/** Instant checks in the browser. Django checks everything again (the real rules live there). */
function validate(form) {
  const e = {}
  if (!form.traveller_is_requester && form.traveller_name.trim().length < 2) e.traveller_name = "Enter the traveller's full name."
  if (!form.traveller_is_requester && form.traveller_phone && !/^\+?[0-9 ()-]{7,20}$/.test(form.traveller_phone.trim()))
    e.traveller_phone = 'Enter a valid phone number.'
  const legErrors = form.legs.map((leg, i) => {
    const le = {}
    const hotel = leg.service === 'HOTEL'
    const origin = leg.origin.trim()
    if (!hotel && !origin) le.origin = 'Where does this journey start?'
    if (!leg.destination.trim()) le.destination = hotel ? 'Which city?' : 'Where does it go?'
    if (!hotel && origin && origin.toLowerCase() === leg.destination.trim().toLowerCase()) le.destination = 'Must differ from the starting point.'
    if (!leg.date) le.date = 'Pick a date.'
    else if (leg.date < todayISO()) le.date = 'This date is in the past.'
    else if (i > 0 && form.legs[i - 1].date && leg.date < form.legs[i - 1].date) le.date = 'Earlier than the booking above: keep travel order.'
    if (hotel && !leg.end_date) le.end_date = 'Pick a check-out date.'
    else if (hotel && leg.end_date <= leg.date) le.end_date = 'Check-out must be after check-in.'
    return le
  })
  if (legErrors.some((le) => Object.keys(le).length)) e.legs = legErrors
  if (form.purpose.trim().length < MIN_PURPOSE) e.purpose = `Please write at least ${MIN_PURPOSE} characters.`
  return e
}

/** Soft hint (not an error): a journey that doesn't start where the previous one ended. */
function gapWarning(legs, i) {
  const leg = legs[i]
  if (i === 0 || leg.service === 'HOTEL' || !leg.origin.trim()) return ''
  const prev = legs[i - 1]
  if (!prev.destination.trim() || leg.origin.trim().toLowerCase() === prev.destination.trim().toLowerCase()) return ''
  return `Starts in ${leg.origin}, but the booking above ends in ${prev.destination}. Is a connection missing?`
}

export default function RequestForm({ user, existing, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState(() => initialForm(existing))
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const noManager = !existing && !user.manager_name
  const legs = form.legs

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
    setErrors((e) => ({ ...e, [field]: undefined, non_field_errors: undefined }))
  }
  function setLegs(next) {
    setForm((f) => ({ ...f, legs: next }))
    setErrors((e) => ({ ...e, legs: undefined, non_field_errors: undefined }))
  }
  const updateLeg = (i, field, value) => setLegs(legs.map((l, j) => (j === i ? { ...l, [field]: value } : l)))

  // A new booking continues from the previous one: same city, same date (or the hotel check-out).
  function addLeg(service) {
    const prev = legs[legs.length - 1]
    setLegs([...legs, newLeg({
      service,
      origin: prev && service !== 'HOTEL' ? prev.destination : '',
      destination: prev && service === 'HOTEL' ? prev.destination : '',
      date: prev ? freeFrom(prev) : '',
    })])
  }

  // Return journey: from wherever the trip ends back to where it started.
  const firstTravel = legs.find((l) => l.service !== 'HOTEL')
  const hasReturn = legs.some((l) => l.is_return)
  function addReturn() {
    const last = legs[legs.length - 1]
    setLegs([...legs, newLeg({
      service: firstTravel.service, origin: last.destination, destination: firstTravel.origin,
      date: freeFrom(last), is_return: true,
    })])
  }

  function move(i, step) {
    const next = [...legs]
    ;[next[i], next[i + step]] = [next[i + step], next[i]]
    setLegs(next)
  }

  async function submit(e) {
    e.preventDefault()
    const problems = validate(form)
    if (Object.keys(problems).length) return setErrors(problems)

    const body = {
      traveller_is_requester: form.traveller_is_requester,
      ...(form.traveller_is_requester ? {} : {
        traveller_name: form.traveller_name.trim(),
        traveller_phone: form.traveller_phone.trim(),
        traveller_email: form.traveller_email.trim(),
      }),
      legs: legs.map((l) => ({
        service: l.service,
        origin: l.service === 'HOTEL' ? '' : l.origin.trim(),
        destination: l.destination.trim(),
        date: l.date,
        end_date: l.service === 'HOTEL' ? l.end_date : null,
        notes: l.notes.trim(),
        is_return: l.is_return,
      })),
      purpose: form.purpose,
      preferences: form.preferences,
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
      // Leg errors come back as one entry per leg: [{}, {date: ["…"]}, …]
      const perLeg = err.status === 400 && Array.isArray(err.data.legs) && typeof err.data.legs[0] === 'object'
      setErrors(perLeg
        ? { ...fieldErrors({ ...err, data: { ...err.data, legs: undefined } }), legs: err.data.legs.map(firstMessages) }
        : fieldErrors(err))
    } finally {
      setBusy(false)
    }
  }

  const legErrs = Array.isArray(errors.legs) ? errors.legs : []
  const dates = legs.flatMap((l) => [l.date, l.service === 'HOTEL' ? l.end_date : '']).filter(Boolean).sort()
  const span = dates.length ? { start_date: dates[0], end_date: dates.at(-1) !== dates[0] ? dates.at(-1) : null } : null

  return (
    <Modal
      title={existing ? `Edit ${existing.request_code}` : 'New travel request'}
      subtitle={existing ? 'Update the details and resubmit for approval.' : user.manager_name && `Goes to ${user.manager_name} for approval.`}
      size="wide" onClose={onClose} onSubmit={submit}
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
      <Alert>{errors.non_field_errors || errors.detail || (typeof errors.legs === 'string' ? errors.legs : '')}</Alert>

      {/* ------------------------------------------------ who travels */}
      <fieldset className="form-section">
        <legend><User size={15} /> Who is travelling?</legend>
        <div className="choice-row">
          <button type="button" className={`choice ${form.traveller_is_requester ? 'selected' : ''}`}
                  onClick={() => set('traveller_is_requester', true)} aria-pressed={form.traveller_is_requester}>
            <User size={18} /><span><strong>Me</strong><small>{user.full_name}</small></span>
          </button>
          <button type="button" className={`choice ${!form.traveller_is_requester ? 'selected' : ''}`}
                  onClick={() => set('traveller_is_requester', false)} aria-pressed={!form.traveller_is_requester}>
            <Users size={18} /><span><strong>Someone else</strong><small>A colleague, guest or client</small></span>
          </button>
        </div>
        {!form.traveller_is_requester && (
          <>
            <div className="grid-3">
              <Field label="Traveller's full name" error={errors.traveller_name}>
                <input value={form.traveller_name} onChange={(e) => set('traveller_name', e.target.value)} maxLength={150} autoFocus />
              </Field>
              <Field label="Phone" optional icon={Phone} error={errors.traveller_phone}>
                <input value={form.traveller_phone} onChange={(e) => set('traveller_phone', e.target.value)} placeholder="+91 98765 43210" maxLength={20} />
              </Field>
              <Field label="Email" optional icon={Mail} error={errors.traveller_email}>
                <input type="email" value={form.traveller_email} onChange={(e) => set('traveller_email', e.target.value)} maxLength={254} />
              </Field>
            </div>
            <p className="hint"><Info size={14} /> You stay the requester: your manager approves it and you get the updates.</p>
          </>
        )}
      </fieldset>

      {/* ------------------------------------------------ itinerary */}
      <fieldset className="form-section">
        <legend><MapPin size={15} /> Itinerary (in travel order)</legend>
        <ol className="itinerary-edit">
          {legs.map((leg, i) => (
            <LegEditor key={leg.key} leg={leg} index={i} count={legs.length} errors={legErrs[i] || {}}
                       warning={gapWarning(legs, i)}
                       onChange={(field, value) => updateLeg(i, field, value)}
                       onMove={(step) => move(i, step)}
                       onRemove={() => setLegs(legs.filter((_, j) => j !== i))} />
          ))}
        </ol>

        <div className="add-legs">
          <span className="subtle xs">Add a booking:</span>
          {SERVICES.map(({ value, label, icon: Icon }) => (
            <button type="button" key={value} className="chip-btn" disabled={legs.length >= MAX_LEGS} onClick={() => addLeg(value)}>
              <Plus size={13} /><Icon size={14} /> {label}
            </button>
          ))}
          {firstTravel && !hasReturn && (
            <button type="button" className="chip-btn accent" disabled={legs.length >= MAX_LEGS} onClick={addReturn}>
              <Undo2 size={14} /> Add return journey
            </button>
          )}
        </div>
        {span && (
          <p className="hint"><CalendarDays size={14} /> {legs.length} booking{legs.length > 1 ? 's' : ''} · {tripLength(span)}</p>
        )}
      </fieldset>

      {/* ------------------------------------------------ why */}
      <Field label="Business purpose" error={errors.purpose}>
        <textarea rows={3} value={form.purpose} onChange={(e) => set('purpose', e.target.value)}
                  placeholder="Who is being met and why is the trip needed?" />
        {!errors.purpose && (
          <div className="field-foot">
            <small className="subtle">Your approver sees this first.</small>
            <small className={form.purpose.trim().length < MIN_PURPOSE ? 'subtle' : 'ok-text'}>{form.purpose.trim().length}/{MIN_PURPOSE}+</small>
          </div>
        )}
      </Field>

      <div className="grid-2">
        <Field label="General preferences" optional>
          <input value={form.preferences} onChange={(e) => set('preferences', e.target.value)} placeholder="Vegetarian meals, near the office…" />
        </Field>
        <Field label="Estimated total cost (₹)" optional error={errors.estimated_cost}>
          <input type="number" min="0" step="0.01" value={form.estimated_cost} onChange={(e) => set('estimated_cost', e.target.value)} placeholder="0" />
        </Field>
      </div>
    </Modal>
  )
}

/** One booking in the itinerary: service + route + date(s) + notes. */
function LegEditor({ leg, index, count, errors, warning, onChange, onMove, onRemove }) {
  const hotel = leg.service === 'HOTEL'
  return (
    <li className="leg-edit">
      <div className="leg-edit-head">
        <span className="leg-number">{index + 1}</span>
        <div className="segmented-sm">
          {SERVICES.map(({ value, label, icon: Icon }) => (
            <button type="button" key={value} className={leg.service === value ? 'on' : ''}
                    onClick={() => onChange('service', value)} aria-pressed={leg.service === value}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>
        {leg.is_return && <span className="badge tone-indigo">Return</span>}
        <div className="leg-tools">
          <button type="button" className="icon-btn sm" disabled={index === 0} onClick={() => onMove(-1)} aria-label="Move up"><ArrowUp size={14} /></button>
          <button type="button" className="icon-btn sm" disabled={index === count - 1} onClick={() => onMove(1)} aria-label="Move down"><ArrowDown size={14} /></button>
          <button type="button" className="icon-btn sm" disabled={count === 1} onClick={onRemove} aria-label="Remove booking"><Trash2 size={14} /></button>
        </div>
      </div>

      <div className="grid-3">
        {!hotel && (
          <Field label="From" icon={MapPin} error={errors.origin}>
            <input value={leg.origin} onChange={(e) => onChange('origin', e.target.value)} placeholder="e.g. Pune" />
          </Field>
        )}
        <Field label={hotel ? 'Hotel city' : 'To'} icon={MapPin} error={errors.destination}>
          <input value={leg.destination} onChange={(e) => onChange('destination', e.target.value)} placeholder="e.g. Delhi" />
        </Field>
        <Field label={hotel ? 'Check-in' : 'Date'} error={errors.date}>
          <input type="date" min={todayISO()} value={leg.date} onChange={(e) => onChange('date', e.target.value)} />
        </Field>
        {hotel && (
          <Field label="Check-out" error={errors.end_date}>
            <input type="date" min={leg.date || todayISO()} value={leg.end_date} onChange={(e) => onChange('end_date', e.target.value)} />
          </Field>
        )}
      </div>
      <input className="leg-notes" value={leg.notes} maxLength={300} onChange={(e) => onChange('notes', e.target.value)}
             placeholder={hotel ? 'Notes: near the office, breakfast included…' : 'Notes: train number / class, morning flight, aisle seat…'} />
      {errors.is_return && <small className="field-error">{errors.is_return}</small>}
      {warning && <small className="warn-text leg-warning"><TriangleAlert size={12} /> {warning}</small>}
    </li>
  )
}

/** Server leg errors look like {date: ["msg"]}; keep the first message per field. */
function firstMessages(legErr) {
  return Object.fromEntries(Object.entries(legErr || {}).map(([k, v]) => [k, [].concat(v)[0]]))
}
