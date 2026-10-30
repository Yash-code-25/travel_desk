import { Plus } from 'lucide-react'
import NotificationBell from './NotificationBell.jsx'
import { Avatar, Button } from './ui.jsx'

export default function Topbar({ page, user, refreshKey, showNewRequest = true, onNewRequest, onOpenRequest, onAccount }) {
  return (
    <header className="topbar">
      <div>
        <h1>{page.title}</h1>
        <p className="subtle">{page.subtitle}</p>
      </div>
      <div className="topbar-actions">
        <NotificationBell refreshKey={refreshKey} onOpenRequest={onOpenRequest} />
        {showNewRequest && (
          <Button kind="primary" icon={Plus} onClick={onNewRequest} aria-label="New request">
            <span className="desktop-only">New request</span><span className="mobile-only">New</span>
          </Button>
        )}
        {/* On phones the sidebar (with your name) becomes a bottom tab bar, so the account button lives here */}
        <button className="icon-btn lg mobile-only" onClick={onAccount} aria-label="Account and sign out">
          <Avatar name={user.full_name} size={30} />
        </button>
      </div>
    </header>
  )
}
