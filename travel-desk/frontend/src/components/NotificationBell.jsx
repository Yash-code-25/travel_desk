import { useRef, useState } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { api } from '../api.js'
import { useClickOutside, useEscape, useVisibleInterval } from '../hooks.js'
import { timeAgo } from '../utils.js'

export default function NotificationBell({ refreshKey, onOpenRequest }) {
  const [data, setData] = useState({ unread: 0, items: [] })
  const [open, setOpen] = useState(false)
  const boxRef = useRef(null)

  // Check for new notifications every 20s while the tab is visible.
  useVisibleInterval(() => api('/notifications/').then(setData).catch(() => {}), 20000, [refreshKey])
  useClickOutside(boxRef, () => setOpen(false), open)
  useEscape(() => setOpen(false), open)

  async function markAllRead() {
    setData((d) => ({ unread: 0, items: d.items.map((n) => ({ ...n, is_read: true })) }))
    await api('/notifications/read/', { method: 'POST' }).catch(() => {})
  }

  return (
    <div className="bell" ref={boxRef}>
      <button className="icon-btn lg" onClick={() => setOpen(!open)} aria-label={`Notifications (${data.unread} unread)`}>
        <Bell size={20} />
        {data.unread > 0 && <span className="bell-count">{data.unread > 9 ? '9+' : data.unread}</span>}
      </button>

      {open && (
        <div className="popover">
          <div className="popover-head">
            <strong>Notifications</strong>
            {data.unread > 0 && <button className="link-btn" onClick={markAllRead}><CheckCheck size={14} /> Mark all read</button>}
          </div>
          <div className="popover-body">
            {data.items.length === 0 && <p className="subtle pad">You're all caught up.</p>}
            {data.items.map((n) => (
              <button key={n.id} className={`notification ${n.is_read ? '' : 'unread'}`}
                      onClick={() => { setOpen(false); if (n.request_id) onOpenRequest(n.request_id) }}>
                {!n.is_read && <i className="unread-dot" />}
                <span className="notification-text">{n.message}</span>
                <span className="subtle xs">{timeAgo(n.created_at)}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
