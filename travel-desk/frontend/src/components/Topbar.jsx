import { Plus } from 'lucide-react'
import NotificationBell from './NotificationBell.jsx'
import { Button } from './ui.jsx'

export default function Topbar({ page, refreshKey, showNewRequest = true, onNewRequest, onOpenRequest }) {
  return (
    <header className="topbar">
      <div>
        <h1>{page.title}</h1>
        <p className="subtle">{page.subtitle}</p>
      </div>
      <div className="topbar-actions">
        <NotificationBell refreshKey={refreshKey} onOpenRequest={onOpenRequest} />
        {showNewRequest && <Button kind="primary" icon={Plus} onClick={onNewRequest}>New request</Button>}
      </div>
    </header>
  )
}
