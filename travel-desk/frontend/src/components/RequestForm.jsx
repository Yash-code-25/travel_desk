// New travel request (one trip, many bookings), or edit a request that was returned for changes.
// Always for the signed-in person. Domestic or international: international trips take the passport,
// visas and forex card from the traveller's profile. Two steps: fill in, then review and submit.
import { useEffect, useState } from 'react'
import {
  ArrowDown, ArrowUp, BookUser, CalendarDays, Check, CreditCard, Globe, MapPin, Pencil, Plane, Plus, Trash2,
  TriangleAlert, Undo2, User,
} from 'lucide-react'
import { api } from '../api.js'
import { COUNTRIES, SERVICE_ICON, SERVICES, TRIP_TYPES } from '../constants.js'
import { fieldErrors, formatDate, legDates, todayISO, tripLength } from '../utils.js'
import Modal from './Modal.jsx'
import { useToast } from './Toast.jsx'
import { Alert, Badge, Banner, Button, Field, Spinner, Toggle } from './ui.jsx'

const MIN_PURPOSE = 10
const MAX_LEGS = 10
const INDIA = 'India'
const PASSPORT_MONTHS_AFTER_TRIP = 6
let nextKey = 1 // stable React keys for legs

const isIntl = (form) => form.trip_type === 'INTERNATIONAL'
const servicesFor = (tripType) => (tripType === 'INTERNATIONAL' ? SERVICES.filter((s) => s.value !== 'TRAIN') : SERVICES)

function newLeg(fields) {
  return {
    key: nextKey++, service: 'FLIGHT', origin: '', origin_country: '', destination: '', destination_country: '',
    date: '', end_date: '', notes: '', is_return: false, ...fields,
  }
}

function initialForm(existing) {
  return {
    trip_type: existing?.trip_type || 'DOMESTIC',
    legs: existing ? existing.legs.map((l) => newLeg({ ...l, end_date: l.end_date || '' })) : [],
    purpose: existing?.purpose || '',
    preferences: existing?.preferences || '',
    estimated_cost: existing?.estimated_cost || '',
    forex_needed: Boolean(existing?.traveller_snapshot?.forex_needed),
  }
}

/** The day you're free for the next booking: the travel date, or the hotel check-out. */
const freeFrom = (leg) => (leg.service === 'HOTEL' && leg.end_date) || leg.date

function tripSpan(legs) {
  const dates = legs.flatMap((l) => [l.date, l.service === 'HOTEL' ? l.end_date : '']).filter(Boolean).sort()
  return dates.length ? { start_date: dates[0], end_date: dates.at(-1) !== dates[0] ? dates.at(-1) : null } : null
}

/** Countries outside India on this trip, in travel order. */
function countriesAbroad(legs) {
  const out = []
  legs.forEach((l) => [l.origin_country, l.destination_country].forEach((c) => {
    if (c && c !== INDIA && !out.includes(c)) out.push(c)
  }))
  return out
}

/** Passport / visa situation for an international trip, from the profile. */
function documentCheck(profile, legs) {
  const span = tripSpan(legs)
  const lastDay = span ? span.end_date || span.start_date : todayISO()
  const needUntil = new Date(lastDay)
  needUntil.setMonth(needUntil.getMonth() + PASSPORT_MONTHS_AFTER_TRIP)
  const needUntilISO = needUntil.toISOString().slice(0, 10)
  const visaFor = (c) => profile.visas.find((v) => v.country === c && v.expiry_date >= lastDay)
  return {
    noPassport: !profile.has_passport,
    passportTooShort: profile.has_passport && profile.passport_expiry_date < needUntilISO,
    needUntilISO,
    visas: countriesAbroad(legs).map((c) => ({ country: c, visa: visaFor(c) })),
  }
}

/** Instant checks in the browser. Django checks everything again (the real rules live there). */
function validate(form, docs) {
  const e = {}
  const intl = isIntl(form)
  const legErrors = form.legs.map((leg, i) => {
    const le = {}
    const hotel = leg.service === 'HOTEL'
    const origin = leg.origin.trim()
    if (intl && leg.service === 'TRAIN') le.service = 'No trains on international trips.'
    if (!hotel && !origin) le.origin = 'Where does this journey start?'
    if (!leg.destination.trim()) le.destination = hotel ? 'Which city?' : 'Where does it go?'
    if (!hotel && origin && origin.toLowerCase() === leg.destination.trim().toLowerCase()) le.destination = 'Must differ from the starting point.'
    if (intl && !hotel && !leg.origin_country) le.origin_country = 'Pick a country.'
    if (intl && !leg.destination_country) le.destination_country = 'Pick a country.'
    if (!leg.date) le.date = 'Pick a date.'
    else if (leg.date < todayISO()) le.date = 'This date is in the past.'
    else if (i > 0 && form.legs[i - 1].date && leg.date < form.legs[i - 1].date) le.date = 'Earlier than the booking above: keep travel order.'
    if (hotel && !leg.end_date) le.end_date = 'Pick a check-out date.'
    else if (hotel && leg.end_date <= leg.date) le.end_date = 'Check-out must be after check-in.'
    return le
  })
  if (legErrors.some((le) => Object.keys(le).length)) e.legs = legErrors
  if (!form.legs.length) e.legs = 'Add at least one booking: flight, hotel, cab or train.'
  if (intl && !e.legs && !countriesAbroad(form.legs).length) e.non_field_errors = 'No booking goes outside India: choose Domestic instead.'
  if (intl && docs?.noPassport) e.non_field_errors = 'International trips need a passport. Add it in My profile first.'
  if (intl && docs?.passportTooShort) e.non_field_errors = 'Your passport must be valid for 6 months after the trip. Renew it and update My profile.'
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

export default function RequestForm({ user, existing, onClose, onSaved, onOpenProfile }) {
  const toast = useToast()
  const [form, setForm] = useState(() => initialForm(existing))
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [profile, setProfile] = useState(null)
  const noManager = !existing && !user.manager_name
  const legs = form.legs
  const intl = isIntl(form)

  // Seat / meal / frequent flyer (all trips) and passport / visas / forex (international) come from the profile.
  useEffect(() => { api('/profile/').then(setProfile).catch(() => {}) }, [])
  const docs = intl && profile ? documentCheck(profile, legs) : null

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
    setErrors((e) => ({ ...e, [field]: undefined, non_field_errors: undefined }))
  }
  function setLegs(next) {
    setForm((f) => ({ ...f, legs: next }))
    setErrors((e) => ({ ...e, legs: undefined, non_field_errors: undefined }))
  }
  const updateLeg = (i, field, value) => setLegs(legs.map((l, j) => (j === i ? { ...l, [field]: value } : l)))

  function chooseTripType(value) {
    // Trains don't exist abroad: switching to international turns them into flights.
    setForm((f) => ({
      ...f, trip_type: value,
      legs: value === 'INTERNATIONAL' ? f.legs.map((l) => (l.service === 'TRAIN' ? { ...l, service: 'FLIGHT' } : l)) : f.legs,
    }))
    setErrors({})
  }

  // A new booking continues from the previous one: same city (and country), same date (or the hotel check-out).
  function addLeg(service) {
    const prev = legs[legs.length - 1]
    setLegs([...legs, newLeg({
      service,
      origin: prev && service !== 'HOTEL' ? prev.destination : '',
      origin_country: prev && service !== 'HOTEL' ? prev.destination_country : '',
      destination: prev && service === 'HOTEL' ? prev.destination : '',
      destination_country: prev && service === 'HOTEL' ? prev.destination_country : '',
      date: prev ? freeFrom(prev) : '',
    })])
  }

  // Return journey: from wherever the trip ends back to where it started.
  const firstTravel = legs.find((l) => l.service !== 'HOTEL')
  const hasReturn = legs.some((l) => l.is_return)
  function addReturn() {
    const last = legs[legs.length - 1]
    setLegs([...legs, newLeg({
      service: firstTravel.service, origin: last.destination, origin_country: last.destination_country,
      destination: firstTravel.origin, destination_country: firstTravel.origin_country,
      date: freeFrom(last), is_return: true,
    })])
  }

  function move(i, step) {
    const next = [...legs]
    ;[next[i], next[i + step]] = [next[i + step], next[i]]
    setLegs(next)
  }

  /** Step 1 -> 2: check everything, then show the summary. */
  function review(e) {
    e.preventDefault()
    const problems = validate(form, docs)
    if (Object.keys(problems).length) return setErrors(problems)
    setReviewing(true)
  }

  async function submit() {
    const body = {
      traveller_is_requester: true,
      trip_type: form.trip_type,
      forex_needed: intl && form.forex_needed,
      legs: legs.map((l) => ({
        service: l.service,
        origin: l.service === 'HOTEL' ? '' : l.origin.trim(),
        origin_country: intl && l.service !== 'HOTEL' ? l.origin_country : '',
        destination: l.destination.trim(),
        destination_country: intl ? l.destination_country : '',
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
      setReviewing(false) // back to the form, where the errors are shown
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
  const span = tripSpan(legs)
  const blocked = noManager || Boolean(intl && (docs?.noPassport || docs?.passportTooShort))

  return (
    <Modal
      title={reviewing ? 'Review your request' : existing ? `Edit ${existing.request_code}` : 'New travel request'}
      subtitle={reviewing ? 'Check everything once more. Nothing is sent until you submit.'
        : existing ? 'Update the details and resubmit for approval.' : user.manager_name && `Goes to ${user.manager_name} for approval.`}
      size="wide" onClose={onClose} onSubmit={reviewing ? (e) => { e.preventDefault(); submit() } : review}
      footer={reviewing ? <>
        <Button type="button" icon={Pencil} onClick={() => setReviewing(false)} disabled={busy}>Back to edit</Button>
        <Button kind="primary" type="submit" icon={Check} loading={busy}>{existing ? 'Save & resubmit' : 'Submit for approval'}</Button>
      </> : <>
        <Button type="button" onClick={onClose}>Cancel</Button>
        <Button kind="primary" type="submit" disabled={blocked}>Review request</Button>
      </>}
    >
      {reviewing ? (
        <ReviewSummary form={form} user={user} profile={profile} docs={docs} span={span} />
      ) : (
        <>
          {noManager && (
            <Banner tone="orange" icon={TriangleAlert} title="No reporting manager set">
              Your request can't be routed for approval. Ask HR/admin to set your manager.
            </Banner>
          )}
          <Alert>{errors.non_field_errors || errors.detail || errors.traveller_is_requester || (typeof errors.legs === 'string' ? errors.legs : '')}</Alert>

          {/* ------------------------------------------------ trip type */}
          <fieldset className="form-section">
            <legend><Globe size={15} /> Where are you travelling?</legend>
            <div className="choice-row">
              {TRIP_TYPES.map((t) => (
                <button type="button" key={t.value} className={`choice ${form.trip_type === t.value ? 'selected' : ''}`}
                        onClick={() => chooseTripType(t.value)} aria-pressed={form.trip_type === t.value}>
                  {t.value === 'INTERNATIONAL' ? <Globe size={18} /> : <MapPin size={18} />}
                  <span><strong>{t.label}</strong><small>{t.text}</small></span>
                </button>
              ))}
            </div>
            <p className="hint"><User size={14} /> Traveller: <strong>{user.full_name}</strong> (requests are always for yourself)</p>
          </fieldset>

          {intl && <DocumentsCard profile={profile} docs={docs} forexNeeded={form.forex_needed}
                                  onForexNeeded={(v) => set('forex_needed', v)} onOpenProfile={onOpenProfile} />}

          {/* ------------------------------------------------ itinerary */}
          <fieldset className="form-section">
            <legend><MapPin size={15} /> Itinerary (in travel order)</legend>
            {legs.length === 0 && <p className="subtle">No bookings yet. Add the first one below.</p>}
            <ol className="itinerary-edit">
              {legs.map((leg, i) => (
                <LegEditor key={leg.key} leg={leg} index={i} count={legs.length} errors={legErrs[i] || {}} tripType={form.trip_type}
                           warning={gapWarning(legs, i)}
                           onChange={(field, value) => updateLeg(i, field, value)}
                           onMove={(step) => move(i, step)}
                           onRemove={() => setLegs(legs.filter((_, j) => j !== i))} />
              ))}
            </ol>

            <div className="add-legs">
              <span className="subtle xs">{legs.length ? 'Add a booking:' : 'Add your first booking:'}</span>
              {servicesFor(form.trip_type).map(({ value, label, icon: Icon }) => (
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
            <Field label="Other preferences" optional hint={profilePrefs(profile) && `From your profile: ${profilePrefs(profile)}`}>
              <input value={form.preferences} onChange={(e) => set('preferences', e.target.value)} placeholder="Near the office, early check-in…" />
            </Field>
            <Field label="Estimated total cost (₹)" optional error={errors.estimated_cost}>
              <input type="number" min="0" step="0.01" value={form.estimated_cost} onChange={(e) => set('estimated_cost', e.target.value)} placeholder="0" />
            </Field>
          </div>
        </>
      )}
    </Modal>
  )
}

/** "Window seat · Vegetarian meal · Air India: AI998877" */
function profilePrefs(p) {
  if (!p) return ''
  return [
    p.seat_preference_label && `${p.seat_preference_label} seat`,
    p.meal_preference_label && `${p.meal_preference_label} meal`,
    ...(p.has_frequent_flyer ? p.frequent_flyers.map((f) => `${f.airline}: ${f.membership_number}`) : []),
  ].filter(Boolean).join(' · ')
}

/** International only: passport, visas and forex card from the profile (read-only). */
function DocumentsCard({ profile, docs, forexNeeded, onForexNeeded, onOpenProfile }) {
  const fixLink = onOpenProfile && <Button type="button" icon={Pencil} onClick={onOpenProfile}>Update my profile</Button>
  if (!profile) return <fieldset className="form-section"><legend><BookUser size={15} /> Travel documents</legend><Spinner /></fieldset>
  return (
    <fieldset className="form-section docs-card">
      <legend><BookUser size={15} /> Travel documents (from your profile)</legend>
      {docs.noPassport ? (
        <Banner tone="red" icon={TriangleAlert} title="No passport in your profile" action={fixLink}>
          International trips need a passport. Add it in My profile, then come back.
        </Banner>
      ) : (
        <>
          <div className="doc-row">
            <span className="doc-label">Passport</span>
            <span><strong>{profile.passport_number}</strong> · valid until {formatDate(profile.passport_expiry_date)}</span>
            {docs.passportTooShort ? <Badge tone="red">Expires too soon</Badge> : <Badge tone="green">OK</Badge>}
          </div>
          {docs.passportTooShort && (
            <Banner tone="red" icon={TriangleAlert} title="Passport must be valid 6 months after the trip" action={fixLink}>
              It needs to be valid until {formatDate(docs.needUntilISO)}. Renew it and update My profile.
            </Banner>
          )}
          {docs.visas.length === 0 && <p className="subtle xs">Pick the countries in the itinerary below to check your visas.</p>}
          {docs.visas.map(({ country, visa }) => (
            <div className="doc-row" key={country}>
              <span className="doc-label">Visa · {country}</span>
              {visa
                ? <><span>{visa.visa_type} · valid until {formatDate(visa.expiry_date)}</span><Badge tone="green">OK</Badge></>
                : <><span className="subtle">No valid visa in your profile: the Travel Desk will be told a visa is needed.</span><Badge tone="amber">Visa needed</Badge></>}
            </div>
          ))}
        </>
      )}
      <div className="doc-row">
        <span className="doc-label"><CreditCard size={13} /> Forex card</span>
        {profile.has_forex_card
          ? <><span>{profile.forex_bank} · card ending {profile.forex_card_last4}</span><Badge tone="green">OK</Badge></>
          : <Toggle checked={forexNeeded} onChange={onForexNeeded} title="Arrange a forex card for me"
                    text="You have no forex card in your profile. Tick this and the Travel Desk will arrange one." />}
      </div>
    </fieldset>
  )
}

/** Step 2: everything on one screen before it is sent. */
function ReviewSummary({ form, user, profile, docs, span }) {
  const intl = isIntl(form)
  const prefs = profilePrefs(profile)
  const where = (city, country) => (intl && country && country !== INDIA ? `${city}, ${country}` : city)
  return (
    <div className="review">
      <div className="review-head">
        <Badge tone={intl ? 'blue' : 'gray'}>{intl ? 'International' : 'Domestic'}</Badge>
        <span><strong>{user.full_name}</strong>{span && <> · {tripLength(span)}</>}</span>
        {user.manager_name && <span className="subtle">· approver: {user.manager_name}</span>}
      </div>

      <section>
        <p className="section-label"><Plane size={14} /> Itinerary</p>
        <ol className="review-legs">
          {form.legs.map((l, i) => {
            const Icon = SERVICE_ICON[l.service]
            return (
              <li key={l.key}>
                <span className="leg-number">{i + 1}</span>
                <Icon size={15} />
                <span>
                  <strong>{l.service === 'HOTEL' ? `Hotel in ${where(l.destination, l.destination_country)}`
                    : `${where(l.origin, l.origin_country)} → ${where(l.destination, l.destination_country)}`}</strong>
                  {l.is_return && <> <Badge tone="indigo">Return</Badge></>}
                  <span className="subtle xs"> · {legDates({ ...l, end_date: l.end_date || null })}</span>
                  {l.notes && <span className="subtle xs block">{l.notes}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      </section>

      {intl && docs && (
        <section>
          <p className="section-label"><BookUser size={14} /> Travel documents</p>
          <ul className="plain-list">
            <li>Passport <strong>{profile.passport_number}</strong>, valid until {formatDate(profile.passport_expiry_date)}</li>
            {docs.visas.map(({ country, visa }) => (
              <li key={country}>{visa ? <>Visa for {country}: {visa.visa_type}, valid until {formatDate(visa.expiry_date)}</>
                : <><Badge tone="amber">Visa needed</Badge> {country}</>}</li>
            ))}
            <li>Forex: {profile.has_forex_card ? `${profile.forex_bank}, card ending ${profile.forex_card_last4}`
              : form.forex_needed ? 'please arrange a forex card' : 'not needed'}</li>
          </ul>
        </section>
      )}

      <section>
        <p className="section-label">Details</p>
        <dl className="details">
          <div className="detail wide"><dt>Business purpose</dt><dd>{form.purpose}</dd></div>
          {prefs && <div className="detail wide"><dt>From your profile</dt><dd>{prefs}</dd></div>}
          {form.preferences && <div className="detail wide"><dt>Other preferences</dt><dd>{form.preferences}</dd></div>}
          <div className="detail"><dt>Estimated cost</dt><dd>{form.estimated_cost ? `₹ ${Number(form.estimated_cost).toLocaleString('en-IN')}` : '—'}</dd></div>
        </dl>
      </section>
    </div>
  )
}

/** One booking in the itinerary: service + route (+ countries abroad) + date(s) + notes. */
function LegEditor({ leg, index, count, errors, warning, tripType, onChange, onMove, onRemove }) {
  const hotel = leg.service === 'HOTEL'
  const intl = tripType === 'INTERNATIONAL'
  const { icon: ServiceIcon, label: serviceLabel } = SERVICES.find((s) => s.value === leg.service)
  const countrySelect = (field) => (
    <select className="field-select" value={leg[field]} onChange={(e) => onChange(field, e.target.value)} aria-label="Country">
      <option value="">Country…</option>
      {COUNTRIES.map((c) => <option key={c}>{c}</option>)}
    </select>
  )
  return (
    <li className="leg-edit">
      <div className="leg-edit-head">
        <span className="leg-number">{index + 1}</span>
        {/* The type is chosen once, with "Add a booking" below; to change it, remove the card and add another. */}
        <span className="leg-type"><ServiceIcon size={15} /> {serviceLabel}</span>
        {leg.is_return && <span className="badge tone-indigo">Return</span>}
        <div className="leg-tools">
          <button type="button" className="icon-btn sm" disabled={index === 0} onClick={() => onMove(-1)} aria-label="Move up"><ArrowUp size={14} /></button>
          <button type="button" className="icon-btn sm" disabled={index === count - 1} onClick={() => onMove(1)} aria-label="Move down"><ArrowDown size={14} /></button>
          <button type="button" className="icon-btn sm" onClick={onRemove} aria-label="Remove booking"><Trash2 size={14} /></button>
        </div>
      </div>
      {errors.service && <small className="field-error">{errors.service}</small>}

      <div className={intl ? 'grid-2' : 'grid-3'}>
        {!hotel && (
          <Field label="From" error={errors.origin || errors.origin_country}>
            <div className={intl ? 'city-country' : ''}>
              <input value={leg.origin} onChange={(e) => onChange('origin', e.target.value)} placeholder={intl ? 'City' : 'e.g. Pune'} />
              {intl && countrySelect('origin_country')}
            </div>
          </Field>
        )}
        <Field label={hotel ? 'Hotel city' : 'To'} error={errors.destination || errors.destination_country}>
          <div className={intl ? 'city-country' : ''}>
            <input value={leg.destination} onChange={(e) => onChange('destination', e.target.value)} placeholder={intl ? 'City' : 'e.g. Delhi'} />
            {intl && countrySelect('destination_country')}
          </div>
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
             placeholder={hotel ? 'Notes: near the office, breakfast included…' : 'Notes: flight / train number, class, morning departure…'} />
      {errors.is_return && <small className="field-error">{errors.is_return}</small>}
      {warning && <small className="warn-text leg-warning"><TriangleAlert size={12} /> {warning}</small>}
    </li>
  )
}

/** Server leg errors look like {date: ["msg"]}; keep the first message per field. */
function firstMessages(legErr) {
  return Object.fromEntries(Object.entries(legErr || {}).map(([k, v]) => [k, [].concat(v)[0]]))
}
