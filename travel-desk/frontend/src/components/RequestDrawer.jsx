// Side panel for one travel request: status, next-step actions, booking, details and history.
import { useCallback, useEffect, useState } from 'react'
import { Check, Download, FileText, TriangleAlert, Upload, X } from 'lucide-react'
import { allErrors, api } from '../api.js'
import { ACTIONS, EVENT_LABELS, SERVICE_ICON, STEPS, STEP_OF, sortActions } from '../constants.js'
import { useEscape } from '../hooks.js'
import { dateRange, formatDateTime, formatMoney, routeText, timeAgo, tripLength } from '../utils.js'
import { useToast } from './Toast.jsx'
import { Alert, Avatar, Banner, Button, Field, Spinner, StatusBadge } from './ui.jsx'

const MAX_TICKET_MB = 5
const TICKET_TYPES = ['pdf', 'png', 'jpg', 'jpeg']
const EMPTY_BOOKING = { booking_reference: '', actual_cost: '', ticket: null }

export default function RequestDrawer({ id, refreshKey, onClose, onChanged, onEdit }) {
  const toast = useToast()
  const [req, setReq] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [active, setActive] = useState(null) // action waiting for a reason / confirmation / booking details
  const [reason, setReason] = useState('')
  const [booking, setBooking] = useState(EMPTY_BOOKING)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false) // disables buttons, so nothing is submitted twice

  const load = useCallback(() =>
    api(`/requests/${id}/`).then((r) => { setReq(r); setLoadError('') }).catch((e) => setLoadError(e.message)), [id])

  function closePanel() {
    setActive(null); setReason(''); setBooking(EMPTY_BOOKING); setError('')
  }

  useEffect(() => { setReq(null); closePanel(); load() }, [id, load])
  useEffect(() => { if (refreshKey) load() }, [refreshKey, load]) // changed elsewhere, e.g. by the edit form

  // Esc closes the open action panel first, then the drawer.
  useEscape(() => (active ? closePanel() : onClose()))

  function start(action) {
    setError('')
    if (action === 'edit') return onEdit(req)
    const meta = ACTIONS[action]
    if (meta.reason || meta.confirm || action === 'book') return setActive(action)
    submit(action)
  }

  async function submit(action) {
    const meta = ACTIONS[action]
    if (meta.reason && !reason.trim()) return setError('Please add a reason. It is shared with everyone involved.')
    if (action === 'book') {
      const problem = checkBooking(booking) // instant feedback; the server checks again
      if (problem) return setError(problem)
    }

    setBusy(true)
    try {
      const updated = await api(`/requests/${id}/act/`, { method: 'POST', body: actionBody(action, reason, booking) })
      setReq(updated)
      closePanel()
      onChanged()
      toast(meta.done)
    } catch (e) {
      setError(allErrors(e))
      if (e.status === 409 || e.status === 404) { load(); onChanged() } // someone else changed it meanwhile
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Request details">
        <header className="drawer-head">
          {req ? (
            <div>
              <div className="drawer-title"><h2>{req.request_code}</h2><StatusBadge status={req.status} /></div>
              <p className="subtle">{req.service_label} · {routeText(req)} · created {timeAgo(req.created_at)}</p>
            </div>
          ) : <div className="subtle">{loadError || 'Loading…'}</div>}
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </header>

        {!req && !loadError && <div className="drawer-loading"><Spinner size={24} /></div>}

        {req && (
          <div className="drawer-body">
            <StatusBanner req={req} />
            <Stepper status={req.status} />

            {req.allowed_actions.length > 0 && (
              <section className="action-card">
                {active ? (
                  <ActionPanel action={active} busy={busy} reason={reason} setReason={setReason}
                               booking={booking} setBooking={setBooking} estimate={req.estimated_cost}
                               onBack={closePanel} onConfirm={() => submit(active)} />
                ) : (
                  <>
                    <p className="section-label">Your next step</p>
                    <div className="action-row">
                      {sortActions(req.allowed_actions).map((a) => (
                        <Button key={a} kind={ACTIONS[a]?.kind} loading={busy} onClick={() => start(a)}>
                          {ACTIONS[a]?.label || a}
                        </Button>
                      ))}
                    </div>
                  </>
                )}
                <Alert>{error}</Alert>
              </section>
            )}

            {req.has_ticket && <TicketCard req={req} />}
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

/** JSON for normal actions; a multipart form when a ticket file is uploaded. */
function actionBody(action, reason, booking) {
  if (action !== 'book') return { action, comment: reason }
  const form = new FormData()
  form.append('action', 'book')
  form.append('comment', reason)
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

/** Reason box / "are you sure?" / booking form for the chosen action. */
function ActionPanel({ action, busy, reason, setReason, booking, setBooking, estimate, onBack, onConfirm }) {
  const meta = ACTIONS[action]
  const isBooking = action === 'book'
  return (
    <div className="confirm-panel">
      <p className="confirm-title">{meta.label}</p>
      {meta.confirm && <p className="subtle">{meta.confirm}</p>}
      {isBooking && <BookingFields booking={booking} setBooking={setBooking} estimate={estimate} />}
      {(meta.reason || isBooking) && (
        <Field label={meta.reason || 'Note for the employee'} optional={isBooking}>
          <textarea autoFocus={!isBooking} rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
                    placeholder="Write a short note…" />
        </Field>
      )}
      <div className="action-row end">
        <Button onClick={onBack} disabled={busy}>Back</Button>
        <Button kind={meta.kind} loading={busy} onClick={onConfirm}>{isBooking ? 'Confirm booking' : meta.label}</Button>
      </div>
    </div>
  )
}

function BookingFields({ booking, setBooking, estimate }) {
  const [dragging, setDragging] = useState(false)
  const set = (field, value) => setBooking({ ...booking, [field]: value })
  const ticket = booking.ticket
  const overBudget = estimate && booking.actual_cost && Number(booking.actual_cost) > Number(estimate) * 1.2

  return (
    <div className="booking-fields">
      <div className="grid-2">
        <Field label="Booking reference / PNR">
          <input autoFocus value={booking.booking_reference} placeholder="e.g. 6E-PNR7XK"
                 onChange={(e) => set('booking_reference', e.target.value)} />
        </Field>
        <Field label="Actual cost (₹)">
          <input type="number" min="0" step="0.01" value={booking.actual_cost} onChange={(e) => set('actual_cost', e.target.value)} />
          {estimate && (
            <small className={overBudget ? 'warn-text' : 'subtle'}>
              Estimate {formatMoney(estimate)}{overBudget && ' · 20%+ over, the manager will be told'}
            </small>
          )}
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

function TicketCard({ req }) {
  return (
    <section className="ticket-card">
      <div>
        <p className="section-label">Booking confirmed</p>
        <p className="ticket-ref">{req.booking_reference}</p>
        <p className="subtle">Paid {formatMoney(req.actual_cost)}{req.desk_agent_name && ` · booked by ${req.desk_agent_name}`}</p>
      </div>
      <a className="btn btn-secondary" href={`/api/requests/${req.id}/ticket/`}><Download size={16} /> Ticket</a>
    </section>
  )
}

function TripDetails({ req }) {
  const ServiceIcon = SERVICE_ICON[req.service]
  const isHotel = req.service === 'HOTEL'
  const rows = [
    ['Traveller', req.employee_name],
    ['Approver', req.approver_name || '—'],
    ['Service', <span className="inline-icon"><ServiceIcon size={14} /> {req.service_label}</span>],
    ['Dates', <>{dateRange(req)}{tripLength(req) && <span className="subtle"> · {tripLength(req)}</span>}</>],
    !isHotel && ['From', req.origin],
    [isHotel ? 'City' : 'To', req.destination],
    ['Estimated cost', formatMoney(req.estimated_cost)],
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
