// Side panel for one travel request: status, next step, itinerary (with per-leg tickets), details and history.
import { useCallback, useEffect, useState } from 'react'
import { Check, Download, FileText, TriangleAlert, Undo2, Upload, X } from 'lucide-react'
import { allErrors, api } from '../api.js'
import { ACTIONS, EVENT_LABELS, SERVICE_ICON, STEPS, STEP_OF, sortActions } from '../constants.js'
import { useEscape } from '../hooks.js'
import { dateRange, formatDateTime, formatMoney, legDates, legRoute, timeAgo, tripLength } from '../utils.js'
import { useToast } from './Toast.jsx'
import { Alert, Avatar, Badge, Banner, Button, Field, Spinner, StatusBadge } from './ui.jsx'

const MAX_TICKET_MB = 5
const TICKET_TYPES = ['pdf', 'png', 'jpg', 'jpeg']
const EMPTY_BOOKING = { booking_reference: '', actual_cost: '', ticket: null }

export default function RequestDrawer({ id, refreshKey, onClose, onChanged, onEdit }) {
  const toast = useToast()
  const [req, setReq] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [active, setActive] = useState(null) // action waiting for a reason / confirmation
  const [reason, setReason] = useState('')
  const [bookingLeg, setBookingLeg] = useState(null) // id of the leg whose ticket is being uploaded
  const [booking, setBooking] = useState(EMPTY_BOOKING)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false) // disables buttons, so nothing is submitted twice

  const load = useCallback(() =>
    api(`/requests/${id}/`).then((r) => { setReq(r); setLoadError('') }).catch((e) => setLoadError(e.message)), [id])

  function closePanels() {
    setActive(null); setReason(''); setBookingLeg(null); setBooking(EMPTY_BOOKING); setError('')
  }

  useEffect(() => { setReq(null); closePanels(); load() }, [id, load])
  useEffect(() => { if (refreshKey) load() }, [refreshKey, load]) // changed elsewhere, e.g. by the edit form

  // Esc closes an open panel first, then the drawer.
  useEscape(() => (active || bookingLeg ? closePanels() : onClose()))

  /** Runs a workflow step on the server and shows the updated request. */
  async function send(body, doneMessage) {
    setBusy(true)
    try {
      const updated = await api(`/requests/${id}/act/`, { method: 'POST', body })
      setReq(updated)
      closePanels()
      onChanged()
      toast(doneMessage(updated))
    } catch (e) {
      setError(allErrors(e))
      if (e.status === 409 || e.status === 404) { load(); onChanged() } // someone else changed it meanwhile
    } finally {
      setBusy(false)
    }
  }

  function start(action) {
    closePanels()
    if (action === 'edit') return onEdit(req)
    const meta = ACTIONS[action]
    if (meta.reason || meta.confirm) return setActive(action)
    send({ action, comment: '' }, () => meta.done)
  }

  function confirmAction() {
    const meta = ACTIONS[active]
    if (meta.reason && !reason.trim()) return setError('Please add a reason. It is shared with everyone involved.')
    send({ action: active, comment: reason }, () => meta.done)
  }

  function saveBooking(leg) {
    const problem = checkBooking(booking) // instant feedback; the server checks again
    if (problem) return setError(problem)
    send(bookingForm(leg.id, booking), (updated) => updated.status === 'BOOKED'
      ? 'All bookings done: the trip is booked and the requester notified'
      : `Booking ${leg.position} saved`)
  }

  const canBook = req?.allowed_actions.includes('book_leg')
  const buttons = req ? sortActions(req.allowed_actions.filter((a) => a !== 'book_leg')) : []
  const booked = req ? req.legs.filter((l) => l.is_booked).length : 0

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Request details">
        <header className="drawer-head">
          {req ? (
            <div>
              <div className="drawer-title"><h2>{req.request_code}</h2><StatusBadge status={req.status} /></div>
              <p className="subtle">{req.route_summary} · created {timeAgo(req.created_at)}</p>
            </div>
          ) : <div className="subtle">{loadError || 'Loading…'}</div>}
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </header>

        {!req && !loadError && <div className="drawer-loading"><Spinner size={24} /></div>}

        {req && (
          <div className="drawer-body">
            <StatusBanner req={req} />
            <Stepper status={req.status} />
            <TravellerCard req={req} />

            {(buttons.length > 0 || canBook) && (
              <section className="action-card">
                {active ? (
                  <ActionPanel action={active} busy={busy} reason={reason} setReason={setReason}
                               onBack={closePanels} onConfirm={confirmAction} />
                ) : (
                  <>
                    <p className="section-label">Your next step</p>
                    {canBook && (
                      <p className="booking-progress">
                        Upload a ticket for each booking below: <strong>{booked} of {req.legs.length} done</strong>.
                        The trip is marked Booked automatically when all are done.
                      </p>
                    )}
                    {buttons.length > 0 && (
                      <div className="action-row">
                        {buttons.map((a) => (
                          <Button key={a} kind={ACTIONS[a]?.kind} loading={busy && !bookingLeg} onClick={() => start(a)}>
                            {ACTIONS[a]?.label || a}
                          </Button>
                        ))}
                      </div>
                    )}
                  </>
                )}
                {!bookingLeg && <Alert>{error}</Alert>}
              </section>
            )}

            <Itinerary req={req} canBook={canBook} bookingLeg={bookingLeg} busy={busy} error={bookingLeg ? error : ''}
                       booking={booking} setBooking={setBooking}
                       onStartBooking={(leg) => { closePanels(); setBookingLeg(leg.id) }}
                       onCancelBooking={closePanels} onSaveBooking={saveBooking} />
            <TripDetails req={req} />
            <Activity events={req.events} />
          </div>
        )}
      </aside>
    </>
  )
}

// ------------------------------------------------------------ helpers
function checkBooking({ booking_reference, actual_cost, ticket }) {
  if (!booking_reference.trim()) return 'Enter the booking reference / PNR.'
  if (actual_cost === '' || Number(actual_cost) < 0) return 'Enter the actual cost (0 or more).'
  if (!ticket) return 'Attach the ticket or booking confirmation.'
  if (!TICKET_TYPES.includes(ticket.name.split('.').pop().toLowerCase())) return 'Ticket must be a PDF, PNG or JPG file.'
  if (ticket.size > MAX_TICKET_MB * 1024 * 1024) return `Ticket is larger than ${MAX_TICKET_MB} MB.`
  return ''
}

/** Multipart form: one leg's booking reference, cost and ticket file. */
function bookingForm(legId, booking) {
  const form = new FormData()
  form.append('action', 'book_leg')
  form.append('leg', legId)
  form.append('booking_reference', booking.booking_reference.trim())
  form.append('actual_cost', booking.actual_cost)
  form.append('ticket', booking.ticket)
  return form
}

// ------------------------------------------------------------ parts of the drawer
/** Plain-language explanation of the current situation, with the latest note. */
function StatusBanner({ req }) {
  const note = req.events[req.events.length - 1]?.comment
  const banners = {
    RETURNED: ['orange', 'Changes requested', note],
    REJECTED: ['red', 'Request rejected', note],
    CANCELLATION_REQUESTED: ['pink', 'Cancellation requested', note],
    CANCELLED: ['gray', 'Request cancelled', note],
    EXPIRED: ['gray', 'Request expired', 'The travel date passed before the trip was booked.'],
  }
  const info = banners[req.status] ||
    (req.is_overdue && ['red', 'Approval overdue', 'This request has been waiting for more than 48 hours.'])
  if (!info) return null
  const [tone, title, text] = info
  return <Banner tone={tone} icon={TriangleAlert} title={title}>{text}</Banner>
}

function Stepper({ status }) {
  const current = STEP_OF[status]
  if (current === undefined) return null // rejected / cancelled / expired: the banner explains it
  const warn = status === 'RETURNED' || status === 'CANCELLATION_REQUESTED'
  return (
    <ol className="stepper">
      {STEPS.map((label, i) => {
        const state = i < current ? 'done' : i === current ? (warn ? 'warn' : 'current') : 'todo'
        return (
          <li key={label} className={`step ${state}`}>
            <span className="step-dot">{state === 'done' ? <Check size={12} strokeWidth={3} /> : i + 1}</span>
            <span className="step-label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}

/** Who travels, and who asked for it when that's someone else. */
function TravellerCard({ req }) {
  const contact = [req.traveller_phone, req.traveller_email].filter(Boolean).join(' · ')
  return (
    <section className="traveller-card">
      <Avatar name={req.traveller_name} size={40} />
      <div>
        <p className="section-label">Traveller</p>
        <strong>{req.traveller_name}</strong>
        {contact && <p className="subtle xs">{contact}</p>}
      </div>
      <div className="requested-by">
        <p className="section-label">Requested by</p>
        <strong>{req.employee_name}</strong>
        {req.traveller_is_requester && <p className="subtle xs">travelling themselves</p>}
      </div>
    </section>
  )
}

/** "Are you sure?" or reason box for the chosen action. */
function ActionPanel({ action, busy, reason, setReason, onBack, onConfirm }) {
  const meta = ACTIONS[action]
  return (
    <div className="confirm-panel">
      <p className="confirm-title">{meta.label}</p>
      {meta.confirm && <p className="subtle">{meta.confirm}</p>}
      {meta.reason && (
        <Field label={meta.reason}>
          <textarea autoFocus rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Write a short note…" />
        </Field>
      )}
      <div className="action-row end">
        <Button onClick={onBack} disabled={busy}>Back</Button>
        <Button kind={meta.kind} loading={busy} onClick={onConfirm}>{meta.label}</Button>
      </div>
    </div>
  )
}

/** Every booking of the trip, each with its own status, ticket and (for the desk) upload form. */
function Itinerary({ req, canBook, bookingLeg, busy, error, booking, setBooking, onStartBooking, onCancelBooking, onSaveBooking }) {
  const showBookingState = ['IN_PROGRESS', 'BOOKED', 'CANCELLATION_REQUESTED', 'COMPLETED', 'CANCELLED'].includes(req.status)
  return (
    <section>
      <p className="section-label">Itinerary · {req.legs.length} booking{req.legs.length > 1 ? 's' : ''}</p>
      <ol className="itinerary">
        {req.legs.map((leg) => {
          const Icon = SERVICE_ICON[leg.service]
          const open = bookingLeg === leg.id
          return (
            <li key={leg.id} className={`leg ${leg.is_booked ? 'booked' : ''}`}>
              <span className="leg-icon"><Icon size={16} /></span>
              <div className="leg-main">
                <div className="leg-title">
                  <strong>{legRoute(leg)}</strong>
                  {leg.is_return && <Badge tone="indigo"><Undo2 size={11} /> Return</Badge>}
                </div>
                <p className="subtle xs">{leg.service_label} · {legDates(leg)}{leg.notes && ` · ${leg.notes}`}</p>

                {leg.is_booked && (
                  <div className="leg-booking">
                    <Badge tone="green">Booked</Badge>
                    <span className="mono">{leg.booking_reference}</span>
                    <span className="subtle xs">{formatMoney(leg.actual_cost)}</span>
                    {leg.has_ticket && (
                      <a className="link-btn" href={`/api/requests/${req.id}/legs/${leg.id}/ticket/`}><Download size={13} /> Ticket</a>
                    )}
                  </div>
                )}
                {!leg.is_booked && showBookingState && <p className="leg-booking"><Badge tone="amber">Not booked yet</Badge></p>}

                {canBook && !open && (
                  <button className="chip-btn leg-book-btn" onClick={() => onStartBooking(leg)}>
                    <Upload size={13} /> {leg.is_booked ? 'Replace ticket' : 'Upload ticket'}
                  </button>
                )}
                {open && (
                  <div className="leg-booking-form">
                    <BookingFields booking={booking} setBooking={setBooking} />
                    <Alert>{error}</Alert>
                    <div className="action-row end">
                      <Button onClick={onCancelBooking} disabled={busy}>Cancel</Button>
                      <Button kind="primary" loading={busy} onClick={() => onSaveBooking(leg)}>Save booking</Button>
                    </div>
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function BookingFields({ booking, setBooking }) {
  const [dragging, setDragging] = useState(false)
  const set = (field, value) => setBooking({ ...booking, [field]: value })
  const ticket = booking.ticket

  return (
    <div className="booking-fields">
      <div className="grid-2">
        <Field label="Booking reference / PNR">
          <input autoFocus value={booking.booking_reference} placeholder="e.g. 6E-PNR7XK"
                 onChange={(e) => set('booking_reference', e.target.value)} />
        </Field>
        <Field label="Cost of this booking (₹)">
          <input type="number" min="0" step="0.01" value={booking.actual_cost} onChange={(e) => set('actual_cost', e.target.value)} />
        </Field>
      </div>

      <label className={`dropzone ${dragging ? 'drag' : ''} ${ticket ? 'has-file' : ''}`}
             onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
             onDragLeave={() => setDragging(false)}
             onDrop={(e) => { e.preventDefault(); setDragging(false); set('ticket', e.dataTransfer.files[0] || null) }}>
        <input type="file" hidden accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => set('ticket', e.target.files[0] || null)} />
        {ticket ? (
          <>
            <FileText size={20} />
            <span><strong>{ticket.name}</strong> <span className="subtle">({Math.ceil(ticket.size / 1024)} KB) · click to change</span></span>
          </>
        ) : (
          <>
            <Upload size={20} />
            <span><strong>Drop the ticket here</strong> or click to browse<br /><span className="subtle xs">PDF, PNG or JPG · max {MAX_TICKET_MB} MB</span></span>
          </>
        )}
      </label>
    </div>
  )
}

function TripDetails({ req }) {
  const rows = [
    ['Travel dates', <>{dateRange(req)} <span className="subtle">· {tripLength(req)}</span></>],
    ['Approver', req.approver_name || '—'],
    ['Estimated cost', formatMoney(req.estimated_cost)],
    ['Actual cost', formatMoney(req.total_actual_cost)],
    ['Desk agent', req.desk_agent_name || '—'],
    ['Business purpose', req.purpose, true],
    req.preferences && ['Preferences', req.preferences, true],
  ].filter(Boolean)

  return (
    <section>
      <p className="section-label">Trip details</p>
      <dl className="details">
        {rows.map(([label, value, wide]) => (
          <div key={label} className={wide ? 'detail wide' : 'detail'}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function Activity({ events }) {
  return (
    <section>
      <p className="section-label">Activity</p>
      <ol className="activity">
        {[...events].reverse().map((ev) => (
          <li key={ev.id}>
            <Avatar name={ev.actor_name} size={28} />
            <div className="activity-body">
              <p><strong>{ev.actor_name}</strong> {EVENT_LABELS[ev.action] || ev.action}</p>
              <span className="subtle xs" title={formatDateTime(ev.created_at)}>{timeAgo(ev.created_at)}</span>
              {ev.comment && <p className="activity-note">{ev.comment}</p>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
