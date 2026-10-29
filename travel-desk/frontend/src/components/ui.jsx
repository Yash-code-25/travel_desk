// Small building blocks used on every screen. Change a style here and it changes everywhere.
import { useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, LoaderCircle, MoreHorizontal, Search, X } from 'lucide-react'
import { STATUS } from '../constants.js'
import { PAGE_SIZE, useClickOutside, useEscape } from '../hooks.js'
import { avatarColor, initials } from '../utils.js'

// ------------------------------------------------------------ basics
export function Spinner({ size = 16 }) {
  return <LoaderCircle size={size} className="spin" />
}

/** kind: primary | secondary | danger. Shows a spinner and disables itself while `loading`. */
export function Button({ kind = 'secondary', loading, icon: Icon, className = '', children, ...props }) {
  return (
    <button className={`btn btn-${kind} ${className}`} disabled={loading || props.disabled} {...props}>
      {loading ? <Spinner /> : Icon && <Icon size={16} />}
      {children}
    </button>
  )
}

/** Coloured pill. tone: green, red, amber, blue, indigo, pink, teal, orange, gray. */
export function Badge({ tone = 'gray', solid, children }) {
  return (
    <span className={`badge tone-${tone} ${solid ? 'solid' : ''}`}>
      {!solid && <i className="badge-dot" />}
      {children}
    </span>
  )
}

export function StatusBadge({ status }) {
  const s = STATUS[status] || { label: status, tone: 'gray' }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

export function Avatar({ name, size = 32 }) {
  return (
    <span className="avatar" style={{ width: size, height: size, background: avatarColor(name), fontSize: size * 0.4 }}>
      {initials(name)}
    </span>
  )
}

// ------------------------------------------------------------ forms
/** Label + input (children) + error or hint underneath. `icon` puts an icon inside the input. */
export function Field({ label, optional, error, hint, icon: Icon, className = '', children }) {
  return (
    <label className={`field ${className}`}>
      <span>{label}{optional && <em>optional</em>}</span>
      {Icon ? <div className="input-icon"><Icon size={16} />{children}</div> : children}
      {error ? <small className="field-error">{error}</small> : hint && <small className="subtle">{hint}</small>}
    </label>
  )
}

/** Big tick-box row with a title and explanation. */
export function Toggle({ checked, onChange, disabled, title, text }) {
  return (
    <label className={`toggle-row ${checked ? 'on' : ''}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span><strong>{title}</strong><br /><small className="subtle">{text}</small></span>
    </label>
  )
}

// ------------------------------------------------------------ messages
/** Coloured message box with an icon, a title and optional text / action button. */
export function Banner({ tone, icon: Icon, title, action, className = '', children }) {
  return (
    <div className={`banner tone-${tone} ${className}`} role={tone === 'red' ? 'alert' : undefined}>
      {Icon && <Icon size={18} />}
      <div className="banner-text">
        {title && <strong>{title}</strong>}
        {children && <p>{children}</p>}
      </div>
      {action}
    </div>
  )
}

export function Alert({ children }) {
  return children ? <div className="alert tone-red" role="alert">{children}</div> : null
}

export function EmptyState({ icon: Icon, title, text, action }) {
  return (
    <div className="empty">
      <span className="empty-icon"><Icon size={22} /></span>
      <strong>{title}</strong>
      {text && <p className="subtle">{text}</p>}
      {action}
    </div>
  )
}

// ------------------------------------------------------------ summary cards
/** Number card. With `onClick` it works as a filter button; `value` undefined shows a loading shimmer. */
export function StatCard({ icon: Icon, label, value, hint, tone = 'slate', selected, onClick }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag className={`stat-card tone-${tone} ${onClick ? '' : 'static'} ${selected ? 'selected' : ''}`}
         onClick={onClick} aria-pressed={onClick ? Boolean(selected) : undefined}>
      <span className="stat-icon"><Icon size={18} /></span>
      <span className="stat-label">{label}</span>
      <span className="stat-value">
        {value === undefined || value === null ? <i className="skeleton sk-num" /> : value}
        {hint && <small className="stat-hint">{hint}</small>}
      </span>
    </Tag>
  )
}

// ------------------------------------------------------------ lists
export function SearchBox({ value, onChange, placeholder }) {
  return (
    <div className="search">
      <Search size={16} />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} maxLength={100} />
      {value && <button className="icon-btn sm" onClick={() => onChange('')} aria-label="Clear search"><X size={14} /></button>}
    </div>
  )
}

/** "Showing 1–15 of 40" + previous/next buttons. Takes the object returned by usePagedList. */
export function Pager({ page, setPage, result, loading }) {
  if (!result?.count) return null
  const from = (page - 1) * PAGE_SIZE + 1
  const to = Math.min(page * PAGE_SIZE, result.count)
  return (
    <div className="pagination">
      <span className="subtle">Showing <strong>{from}–{to}</strong> of <strong>{result.count}</strong></span>
      <div className="pager">
        <button className="icon-btn bordered" disabled={!result.previous || loading} onClick={() => setPage(page - 1)} aria-label="Previous page">
          <ChevronLeft size={16} />
        </button>
        <span className="subtle">Page {page} of {Math.ceil(result.count / PAGE_SIZE)}</span>
        <button className="icon-btn bordered" disabled={!result.next || loading} onClick={() => setPage(page + 1)} aria-label="Next page">
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  )
}

/** "⋯" button with a drop-down list of actions: [{ icon, label, onClick, danger }]. */
export function ActionMenu({ items, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useClickOutside(ref, () => setOpen(false), open)
  useEscape(() => setOpen(false), open)

  return (
    <div className="row-menu" ref={ref}>
      <button className="icon-btn bordered" disabled={disabled} onClick={() => setOpen(!open)} aria-label="Actions" aria-expanded={open}>
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div className="menu">
          {items.map(({ icon: Icon, label, onClick, danger }) => (
            <button key={label} className={danger ? 'danger' : ''} onClick={() => { setOpen(false); onClick() }}>
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
