import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { api } from './api.js'
import { EMPLOYEES_PAGE, PAGES, SECURITY_PAGE } from './constants.js'
import { useVisibleInterval } from './hooks.js'
import AccountDialog from './components/AccountDialog.jsx'
import EmployeesPage from './components/EmployeesPage.jsx'
import FirstLogin from './components/FirstLogin.jsx'
import Login from './components/Login.jsx'
import ProfileSetup from './components/ProfileSetup.jsx'
import { ProfileDialog } from './components/ProfileView.jsx'
import RequestDrawer from './components/RequestDrawer.jsx'
import RequestForm from './components/RequestForm.jsx'
import RequestsPage from './components/RequestsPage.jsx'
import SecurityPage from './components/SecurityPage.jsx'
import Sidebar from './components/Sidebar.jsx'
import Topbar from './components/Topbar.jsx'
import { useToast } from './components/Toast.jsx'
import { Banner, Button, Spinner } from './components/ui.jsx'

/** Which pages a person sees follows their role. */
function pagesFor(user) {
  const pages = ['mine']
  if (user.is_approver) pages.push('approvals')
  if (user.is_travel_manager) pages.push('manage')
  if (user.is_desk) pages.push('desk')
  if (user.is_superuser) pages.push('employees', 'security')
  return pages
}

export default function App() {
  const toast = useToast()
  const [user, setUser] = useState(undefined) // undefined = still checking, null = signed out
  const [config, setConfig] = useState({ demo_mode: false, demo_users: [] })
  const [page, setPage] = useState('mine')
  const [openId, setOpenId] = useState(null) // request shown in the side drawer
  const [formFor, setFormFor] = useState(null) // null = closed, {} = new request, { request } = edit
  const [accountOpen, setAccountOpen] = useState(null) // null = closed, else the tab to show
  const [profileOf, setProfileOf] = useState(null) // someone's travel profile (Travel Desk / administrators)
  const [refreshKey, setRefreshKey] = useState(0) // bump to reload lists and counts

  const refresh = () => setRefreshKey((k) => k + 1)
  const reloadMe = () => api('/auth/me/').then((d) => d.user && setUser(d.user)).catch(() => {})

  // Page load: get the CSRF cookie and sign-in options, then ask "who am I?".
  useEffect(() => {
    api('/auth/csrf/')
      .then((c) => { setConfig(c); return api('/auth/me/') })
      .then((d) => setUser(d.user))
      .catch(() => setUser(null))
  }, [])

  // Session expired, revoked or account deactivated: back to sign-in.
  useEffect(() => {
    const onExpired = () => {
      setUser((u) => {
        if (u) toast('Your session has ended. Please sign in again.', 'info')
        return null
      })
      setOpenId(null); setFormFor(null); setAccountOpen(null); setProfileOf(null)
    }
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [toast])

  // Sidebar counts after every change, and every minute so role changes by an admin show up.
  useEffect(() => { if (user && refreshKey > 0) reloadMe() }, [refreshKey])
  useVisibleInterval(() => user && reloadMe(), 60000, [Boolean(user)])

  async function logout() {
    await api('/auth/logout/', { method: 'POST' }).catch(() => {})
    setUser(null); setPage('mine'); setOpenId(null)
  }

  if (user === undefined) return <div className="fullscreen-center"><Spinner size={28} /></div>
  if (user === null) return <Login config={config} onLogin={(u) => { setUser(u); setPage('mine') }} />
  if (user.must_change_password) return <FirstLogin user={user} onDone={setUser} onLogout={logout} />
  if (!user.profile_complete) return <ProfileSetup user={user} onDone={setUser} onLogout={logout} />

  const pages = pagesFor(user)
  const current = pages.includes(page) ? page : 'mine'
  const adminPage = { employees: EMPLOYEES_PAGE, security: SECURITY_PAGE }[current]
  const newRequest = () => setFormFor({})

  return (
    <div className="layout">
      <Sidebar user={user} pages={pages} current={current} onNavigate={setPage}
               onLogout={logout} onAccount={() => setAccountOpen('profile')} />

      <main className="main">
        {user.password_weak && (
          <Banner tone="orange" icon={ShieldAlert} className="weak-banner" title="Your password is weak"
                  action={<Button onClick={() => setAccountOpen('security')}>Change password</Button>}>
            It doesn't meet the company password policy. Change it to keep your account safe.
          </Banner>
        )}

        <Topbar page={adminPage || PAGES[current]} user={user} refreshKey={refreshKey} showNewRequest={!adminPage}
                onNewRequest={newRequest} onOpenRequest={setOpenId} onAccount={() => setAccountOpen('profile')} />

        {current === 'employees' && <EmployeesPage me={user} onPeopleChanged={refresh} onViewProfile={setProfileOf} />}
        {current === 'security' && <SecurityPage onGoToEmployees={() => setPage('employees')} />}
        {!adminPage && (
          // key= gives each workspace its own fresh filters
          <RequestsPage key={current} scope={current} refreshKey={refreshKey} onOpen={setOpenId} onNewRequest={newRequest} />
        )}
      </main>

      {openId && (
        <RequestDrawer id={openId} refreshKey={refreshKey} onClose={() => setOpenId(null)}
                       onChanged={refresh} onEdit={(request) => setFormFor({ request })}
                       onViewProfile={user.is_desk || user.is_superuser ? setProfileOf : null} />
      )}

      {formFor && (
        <RequestForm user={user} existing={formFor.request} onClose={() => setFormFor(null)}
                     onOpenProfile={() => { setFormFor(null); setAccountOpen('profile') }}
                     onSaved={(saved) => { setFormFor(null); refresh(); setOpenId(saved.id) }} />
      )}

      {accountOpen && (
        <AccountDialog user={user} initialTab={accountOpen} onClose={() => setAccountOpen(null)} onUpdated={setUser} onLogout={logout} />
      )}

      {profileOf && <ProfileDialog userId={profileOf} onClose={() => setProfileOf(null)} />}
    </div>
  )
}
