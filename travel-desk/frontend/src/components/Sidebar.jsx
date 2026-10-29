import { LogOut, Plane, Settings } from 'lucide-react'
import { EMPLOYEES_PAGE, PAGES, SECURITY_PAGE } from '../constants.js'
import { Avatar } from './ui.jsx'

export default function Sidebar({ user, pages, current, onNavigate, onLogout, onAccount }) {
  const counts = { approvals: user.counts.pending_approvals, desk: user.counts.desk_queue }
  const workspace = pages.filter((p) => PAGES[p])

  const item = (key, { title, icon: Icon }) => (
    <button key={key} className={`nav-item ${current === key ? 'active' : ''}`}
            onClick={() => onNavigate(key)} aria-current={current === key ? 'page' : undefined}>
      <Icon size={18} />
      <span>{title}</span>
      {counts[key] > 0 && <span className="nav-count">{counts[key]}</span>}
    </button>
  )

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark"><Plane size={18} /></span>
        <span className="brand-name">Travel Desk</span>
      </div>

      <nav className="nav">
        <p className="nav-label">Workspace</p>
        {workspace.map((key) => item(key, PAGES[key]))}
        {pages.includes('security') && (
          <>
            <p className="nav-label spaced">Administration</p>
            {item('employees', EMPLOYEES_PAGE)}
            {item('security', SECURITY_PAGE)}
          </>
        )}
      </nav>

      <div className="user-card">
        <button className="user-card-main" onClick={onAccount} title="Account & security">
          <Avatar name={user.full_name} size={36} />
          <span className="user-meta">
            <strong>{user.full_name}</strong>
            <span>{user.role_label}{user.manager_name ? ` · reports to ${user.manager_name.split(' ')[0]}` : ''}</span>
          </span>
          <Settings size={16} className="user-card-gear" />
        </button>
        <button className="icon-btn" onClick={onLogout} title="Log out" aria-label="Log out">
          <LogOut size={18} />
        </button>
      </div>
    </aside>
  )
}
