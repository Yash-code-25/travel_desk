# Travel Desk — Django + React

Full booking approval flow: **Employee → Manager → Travel Desk**, with login, roles,
audit history, notifications, ticket upload and edge cases handled on the server.

## Run it (two terminals)

**Terminal 1 – Django API (port 8001)**
```
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py createcachetable         # shared cache for lockouts & rate limits
python manage.py createsuperuser          # your administrator account (Security panel + Django admin)
python manage.py seed_demo --with-trips   # demo users (password demo1234) + 9 sample trips — DEBUG only
python manage.py runserver 8001
```
(Leave out `--with-trips` for an empty system. Django admin is at `/secure-admin/`, not `/admin/`.)

**Terminal 2 – React (port 5174)**
```
cd frontend
npm install
npm run dev
```
Open http://localhost:5174 and click a demo user to sign in.

**Tests:** `cd backend` then `python manage.py test desk` (74 tests: workflow edge cases, speed, security, employee admin).
**Daily job (optional cron):** `python manage.py auto_close`

## UI at a glance
- **Sidebar** with My trips / Approvals / Travel desk (with live counts) and your profile
- **Summary cards** on every page that double as filters (e.g. *Waiting for you*, *Overdue*, *New in queue*)
- **Table** with server-side search, sorting, pagination, loading skeletons and empty states;
  a blue dot marks rows waiting on *you*
- **Side drawer** for each request: progress stepper, plain-language status banner,
  "Your next step" actions (reason box / confirmation / booking form appear inline),
  booking card with ticket download, trip details and activity timeline
- **Toasts** confirm every action; **Esc** closes panels; works on mobile

## Performance
| What | How |
|---|---|
| No N+1 queries | Lists cost the same number of queries for 2 or 200 rows (tested); user role is cached per request |
| Small payloads | Lists use a light serializer (no history/long text); pages of 15; gzip on |
| Search in the DB | Status / overdue / text filters run as SQL, not in the browser |
| Dashboard counts | One `GROUP BY` query instead of loading rows |
| Indexes | `(employee,status)`, `(approver,status)`, `(status,start_date)`, `(user,is_read)` |
| Background rules | Auto-expire/complete runs in bulk at most once a minute, not on every request |
| Frontend | Debounced search, stale requests cancelled, notification polling pauses in hidden tabs |

## Demo users
| User | Role | Notes |
|---|---|---|
| asha, ravi | Employee | Manager = meera |
| meera | Manager | Approves asha & ravi; her own trips go to director |
| director | Manager | Approves meera, deepak, sara |
| deepak, sara | Travel Desk | Pick up, book, handle cancellations |
| newjoiner | Employee | **No manager set** – shows the "can't route" error |

## Status flow
```
                ┌──── return (reason) ────┐
                ▼                         │
submit → PENDING_APPROVAL ── approve ──► APPROVED ── pick_up ──► IN_PROGRESS ── book ──► BOOKED ──► COMPLETED
   ▲            │                          ▲                        │   │                  │
   │            └─ reject (reason) ─► REJECTED          release ────┘   │      request_cancel (reason)
   │                                                                     │                  ▼
   └──── resubmit / edit ◄──── RETURNED ◄──── unavailable (reason) ──────┘     CANCELLATION_REQUESTED
                                                                               confirm ▼     ▲ decline → BOOKED
Owner can cancel any time before BOOKED → CANCELLED                                CANCELLED
Travel date passes before booking → EXPIRED (automatic)
```

## Edge cases handled
**Request form**
- Required fields; purpose at least 10 characters
- Travel date not in the past, max 365 days ahead, trip max 60 days
- Return date not before departure; hotel check-out must be after check-in
- From and To can't be the same city (case/space-insensitive)
- Hotels don't need a "From" city (it is ignored)
- Duplicate check: same service + destination + overlapping dates while another request is still active
- Employee with no (or inactive) manager can't submit — clear message to contact HR

**Approvals**
- Only the assigned manager can approve; nobody can approve their own request
- A manager's own trip goes to *their* manager
- Reject / Return need a reason
- Double-click or two tabs: second click gets "already updated" (409), DB row is locked during the change
- Can't approve after the travel date passed; such requests auto-expire
- Pending more than 48h is flagged **Overdue**
- Returned → employee edits (re-validated) → goes back for approval;
  if the manager changed meanwhile, it goes to the new manager

**Travel Desk**
- Only desk staff see the queue; two agents can't pick up the same request
- Only the agent who picked it up can book / return it; they can put it back in the queue
- "Not available" sends it back to the employee with a reason; re-approval needed after changes
- Booking needs PNR/reference, a valid cost and a ticket file (PDF/PNG/JPG, max 5 MB, not empty)
- Actual cost 20%+ above the estimate → noted in history and the manager is notified
- Can't mark completed before the trip starts; finished trips auto-complete

**Cancellation**
- Owner cancels freely before booking; after booking they must *request* cancellation (with reason)
- Desk confirms or declines (declining needs a reason); can't request after trip started
- Final states (Rejected, Cancelled, Completed, Expired) allow no further actions

**Data access**
- Login required for every API; employees only see their own requests (others get 404)
- Tickets are downloaded through a permission-checked API, not a public URL
- Requests are never deleted (no DELETE) — full audit history of who did what and when

## Employees (administrators only — sidebar → *Employees*)
- **Register employee**: name, work email, phone, employee ID, department, designation (job title),
  portal role, reporting manager, optional Administrator rights
- A username is suggested from the name (`asha.patil`, `asha.patil2`…) and a random temporary password is created
- **Login details are emailed** (username + temporary password + sign-in link) and shown to the admin **once**
- At first sign-in the person must choose their own password; until then the server blocks everything else
- **Edit** details / role / manager / active / admin, **Reset password** (new temporary password emailed,
  signed out everywhere), **Unlock**, **Sign out everywhere**, **Deactivate / Reactivate**
- Cards to filter by role (Employees, Managers, Travel Desk, Administrators, Inactive) and search by name, ID, department…

**What each role can do in the portal**
| Role | Sees | Can |
|---|---|---|
| Employee | My trips | Raise and track own requests, cancel them |
| Manager | My trips + Approvals (when people report to them) | Approve / return / reject their team's requests |
| Travel Desk | My trips + Travel desk | Book approved trips, upload tickets, handle cancellations |
| Administrator (extra right) | + Employees, Security | Register people, change access, read the security log |

Menus update within a minute when an admin changes someone's role. **Open work follows people changes:**
- new manager → the employee's pending requests move to the new manager
- manager deactivated → their pending approvals escalate to *their* manager
- desk agent deactivated or moved off the desk → bookings they were working on go back to the desk queue

**Email setup** (otherwise emails are printed in the Django terminal):
```
DJANGO_EMAIL_HOST=smtp.office365.com      # or smtp.gmail.com / your company's SMTP server
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_USER=traveldesk@yourcompany.in
DJANGO_EMAIL_PASSWORD=<app password>
DJANGO_FROM_EMAIL=Travel Desk <traveldesk@yourcompany.in>
DJANGO_PORTAL_URL=https://travel.yourcompany.in
```

## Security
**Security panel** (administrators / superusers only — sidebar → *Security*)
- Cards: sign-ins, failed sign-ins, lockouts and blocked actions in the last 24h; locked accounts; users
- **Security log**: every sign-in, failed sign-in, lockout, password change, permission-denied attempt,
  rejected upload and admin change — with IP address, device and who did it; searchable and filterable
- Click a card (failed sign-ins, lockouts, blocked actions) to filter the log; locked accounts are listed with a link to unlock them
- The log is read-only, also in Django admin

**Every user** (click your name, bottom left → *Account & security*)
- Change password (policy-checked, strength meter); other devices are signed out automatically
- Own recent sign-in activity; a banner nags if the current password is weak

| Protection | Details |
|---|---|
| Brute-force lockout | 5 wrong passwords → that username locked 15 min; 20 per IP → IP locked. Applies to the app **and** Django admin |
| Rate limits | Sign-in / password change: 10 per minute per IP; API: 60/min anonymous, 600/min signed-in |
| No user enumeration | Same message for "wrong password" and "no such user" |
| Password policy | Min 10 chars, not common, not all digits, not similar to name; checked on change |
| Sessions | HttpOnly + SameSite cookies, new session id at sign-in, 2 h idle timeout, revoked on deactivation / password change / admin "sign out" |
| Expired session | API answers 401 and the app returns to the sign-in page |
| CSRF | Token required on every change |
| Headers | CSP `default-src 'none'` + `no-store` on API, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, COOP |
| Uploads | Extension + size + **real file signature** check (a renamed .exe is rejected and logged) |
| Input limits | Length caps on all free text, search terms and request body size |
| Admin safety | Can't deactivate yourself or the last admin; no manager loops; every change logged with your name |
| Demo mode | One-click demo users only when `DJANGO_DEBUG` is on; password never sent to the browser; `seed_demo` refuses to run in production |
| Hidden surfaces | Django admin at `/secure-admin/` (configurable), no browsable API, no public API index |
| Production settings | From environment: `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY` (required), `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_ADMIN_URL`. With DEBUG off: HTTPS redirect, HSTS (1 year), Secure cookies |

**Production checklist:** set the environment variables above, serve over HTTPS behind a reverse proxy
(nginx) that also sends a CSP for the React files, use PostgreSQL + Redis, and give every administrator a strong unique password.

## Where things are
| File | What it does |
|---|---|
| `backend/desk/services.py` | **All workflow rules** (who can do what, from which status) |
| `backend/desk/serializers.py` | Form validation rules |
| `backend/desk/views.py` | API endpoints |
| `backend/desk/models.py` | Profile, TravelRequest, RequestEvent (history), SecurityEvent (security log), Notification |
| `backend/desk/security.py` | Lockout, audit log, session revoke, file signature check |
| `backend/desk/security_views.py` | Employees + security panel API (superusers only) |
| `backend/desk/employees.py` | Temporary passwords, welcome emails, moving open work when people change |
| `frontend/src/components/EmployeesPage.jsx`, `EmployeeForm.jsx` | Employee list, register / edit form |
| `frontend/src/components/FirstLogin.jsx` | "Choose your password" screen at first sign-in |
| `backend/desk/middleware.py` | Extra security headers |
| `backend/desk/tests.py`, `test_security.py` | Workflow edge cases / security tests |
| `frontend/src/api.js` | Fetch helper (CSRF, JSON, file upload, errors, session expiry) |
| `frontend/src/hooks.js` | Reusable hooks: `usePagedList` (server lists), `useDebounced`, `useEscape`, `useClickOutside`, `useVisibleInterval` |
| `frontend/src/components/ui.jsx` | Shared building blocks: Button, Badge, StatusBadge, Avatar, Field, Toggle, Banner, Alert, EmptyState, StatCard, SearchBox, Pager, ActionMenu |
| `frontend/src/components/Modal.jsx` | Every pop-up window (`Modal`) and the "Are you sure?" box (`ConfirmDialog`) |
| `frontend/src/utils.js` | Plain helpers: dates, money, trip text, initials, device name, error formatting |
| `frontend/src/App.jsx` | Login check, pages, opens form/drawer/account dialog |
| `frontend/src/components/SecurityPage.jsx` | Security panel |
| `frontend/src/components/AccountDialog.jsx` | Change password + own activity |
| `frontend/src/components/RequestDrawer.jsx` | Details, history, action buttons (server decides which) |
| `frontend/src/components/RequestForm.jsx` | New / edit form |

## Not included yet (next steps)
- Company SSO (Microsoft/Google) instead of username/password, and two-factor sign-in for administrators
- Real email sending (now printed to the Django console) and reminder emails for overdue approvals
- Spending limits per grade / second-level approval for expensive trips
- PostgreSQL instead of SQLite for production
