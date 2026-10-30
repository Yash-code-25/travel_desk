import {
  Briefcase, Car, CircleCheck, Clock, Hotel, Hourglass, Inbox, Layers, LoaderCircle,
  PenLine, Plane, ShieldCheck, Ticket, TrainFront, TriangleAlert, Ban, Users, Gauge,
} from 'lucide-react'

export const SERVICES = [
  { value: 'FLIGHT', label: 'Flight', icon: Plane },
  { value: 'TRAIN', label: 'Train', icon: TrainFront },
  { value: 'HOTEL', label: 'Hotel', icon: Hotel },
  { value: 'CAB', label: 'Cab', icon: Car },
]
export const SERVICE_ICON = Object.fromEntries(SERVICES.map((s) => [s.value, s.icon]))

// tone = colour family used by badges, cards and banners (see style.css .tone-*)
export const STATUS = {
  PENDING_APPROVAL: { label: 'Pending approval', tone: 'amber' },
  RETURNED: { label: 'Changes requested', tone: 'orange' },
  REJECTED: { label: 'Rejected', tone: 'red' },
  APPROVED: { label: 'Waiting to be assigned', tone: 'indigo' },
  IN_PROGRESS: { label: 'Booking in progress', tone: 'blue' },
  BOOKED: { label: 'Booked', tone: 'green' },
  CANCELLATION_REQUESTED: { label: 'Cancellation requested', tone: 'pink' },
  CANCELLED: { label: 'Cancelled', tone: 'gray' },
  COMPLETED: { label: 'Completed', tone: 'teal' },
  EXPIRED: { label: 'Expired', tone: 'gray' },
}

// The three workspaces and their summary cards. Each card is also a filter.
export const PAGES = {
  mine: {
    title: 'My trips',
    subtitle: 'Raise travel requests and follow them from approval to ticket.',
    icon: Briefcase,
    defaultCard: 'all',
    empty: 'You have no travel requests yet.',
    emptyText: 'Raise a request and follow it from approval to ticket.',
    cards: [
      { key: 'all', label: 'All requests', icon: Layers, tone: 'slate' },
      { key: 'pending', label: 'Awaiting approval', statuses: ['PENDING_APPROVAL'], icon: Clock, tone: 'amber' },
      { key: 'changes', label: 'Needs your changes', statuses: ['RETURNED'], icon: PenLine, tone: 'orange' },
      { key: 'booking', label: 'Being booked', statuses: ['APPROVED', 'IN_PROGRESS'], icon: LoaderCircle, tone: 'blue' },
      { key: 'booked', label: 'Booked', statuses: ['BOOKED', 'CANCELLATION_REQUESTED'], icon: Ticket, tone: 'green' },
    ],
  },
  approvals: {
    title: 'Approvals',
    subtitle: 'Travel requests from your team waiting for your decision.',
    icon: CircleCheck,
    defaultCard: 'waiting',
    empty: 'Nothing here. You are all caught up.',
    emptyText: 'Requests from your team appear here when they need your decision.',
    cards: [
      { key: 'waiting', label: 'Waiting for you', statuses: ['PENDING_APPROVAL'], icon: Inbox, tone: 'amber' },
      { key: 'overdue', label: 'Overdue (48h+)', overdue: true, icon: TriangleAlert, tone: 'red' },
      { key: 'approved', label: 'Approved', statuses: ['APPROVED', 'IN_PROGRESS', 'BOOKED', 'CANCELLATION_REQUESTED', 'COMPLETED'], icon: CircleCheck, tone: 'green' },
      { key: 'closed', label: 'Not approved', statuses: ['RETURNED', 'REJECTED'], icon: Ban, tone: 'slate' },
      { key: 'all', label: 'All', icon: Layers, tone: 'slate' },
    ],
  },
  // Travel Managers: every approved trip, to assign, reassign or book themselves. Plus analytics.
  manage: {
    title: 'Travel manager',
    subtitle: 'Assign approved trips to the Travel Desk, follow progress and see how the desk is doing.',
    icon: Gauge,
    defaultCard: 'waiting',
    empty: 'No trips are waiting to be assigned.',
    emptyText: 'Approved trips land here first, ready for you to assign.',
    showAgent: true,
    cards: [
      { key: 'waiting', label: 'Waiting to assign', statuses: ['APPROVED'], icon: Inbox, tone: 'indigo' },
      { key: 'progress', label: 'Being booked', statuses: ['IN_PROGRESS'], icon: Hourglass, tone: 'blue' },
      { key: 'cancel', label: 'Cancellation requests', statuses: ['CANCELLATION_REQUESTED'], icon: Ban, tone: 'pink' },
      { key: 'booked', label: 'Booked', statuses: ['BOOKED'], icon: Ticket, tone: 'green' },
      { key: 'all', label: 'All', icon: Layers, tone: 'slate' },
    ],
  },
  // Agents (and Travel Managers' own bookings): only trips assigned to them.
  desk: {
    title: 'My assignments',
    subtitle: 'Trips assigned to you: book each ticket, upload it, and handle cancellations.',
    icon: Ticket,
    defaultCard: 'progress',
    empty: 'Nothing assigned to you right now.',
    emptyText: 'Your Travel Manager assigns trips to you; they appear here to book.',
    cards: [
      { key: 'progress', label: 'To book', statuses: ['IN_PROGRESS'], icon: Hourglass, tone: 'blue' },
      { key: 'cancel', label: 'Cancellation requests', statuses: ['CANCELLATION_REQUESTED'], icon: Ban, tone: 'pink' },
      { key: 'booked', label: 'Booked', statuses: ['BOOKED'], icon: Ticket, tone: 'green' },
      { key: 'all', label: 'All', icon: Layers, tone: 'slate' },
    ],
  },
}

// Administrator-only page (not a request list).
export const SECURITY_PAGE = {
  title: 'Security',
  subtitle: 'Sign-in activity, lockouts and user access across the organisation.',
  icon: ShieldCheck,
}

// Security log event types -> colour of their badge.
export const EVENT_TONES = {
  LOGIN_SUCCESS: 'green', LOGOUT: 'gray', LOGIN_FAILED: 'amber', LOCKED_OUT: 'red', LOCKED_ATTEMPT: 'red',
  PASSWORD_CHANGED: 'blue', PASSWORD_CHANGE_FAILED: 'amber', USER_UPDATED: 'indigo', ACCOUNT_UNLOCKED: 'teal',
  SESSIONS_REVOKED: 'pink', PERMISSION_DENIED: 'orange', UPLOAD_REJECTED: 'red',
  USER_CREATED: 'green', PASSWORD_RESET: 'blue',
}

export const EMPLOYEES_PAGE = {
  title: 'Employees',
  subtitle: 'Register people, set their position and reporting line, and control what they can do.',
  icon: Users,
}

// Portal role = what someone can do. (Their job title is the free-text "designation".)
export const ROLES = [
  { value: 'EMPLOYEE', label: 'Employee', tone: 'slate',
    can: 'Raise travel requests and track their own trips.' },
  { value: 'MANAGER', label: 'Manager', tone: 'amber',
    can: 'Everything an employee can, plus approve, return or reject requests from people who report to them.' },
  { value: 'DESK', label: 'Travel Desk', tone: 'blue',
    can: 'Everything an employee can, plus book the trips assigned to them, upload tickets and handle cancellations.' },
  { value: 'TRAVEL_MGR', label: 'Travel Manager', tone: 'teal',
    can: 'Gets every approved trip: assigns it to a Travel Desk agent or books it, reassigns, and sees desk analytics.' },
]
export const ROLE_BY_VALUE = Object.fromEntries(ROLES.map((r) => [r.value, r]))

// How each workflow action looks. The SERVER decides which ones a user gets.
//   reason: needs a written reason   confirm: ask "are you sure?" first   done: toast text
export const ACTIONS = {
  edit:           { label: 'Edit & resubmit', kind: 'primary' },
  approve:        { label: 'Approve', kind: 'primary', done: 'Approved and sent to the Travel Desk' },
  assign:         { label: 'Assign to agent', kind: 'primary', picker: true },
  pick_up:        { label: 'Book it myself', kind: 'secondary', done: 'Assigned to you' },
  resubmit:       { label: 'Resubmit as is', kind: 'secondary', done: 'Resubmitted for approval' },
  return:         { label: 'Request changes', kind: 'secondary', reason: 'What should be changed?', done: 'Sent back to the employee' },
  unavailable:    { label: 'Not available', kind: 'secondary', reason: 'What is unavailable? Suggest alternatives.', done: 'Sent back to the employee' },
  release:        { label: 'Unassign', kind: 'secondary', confirm: 'Take this trip off the agent? It goes back to "Waiting to be assigned".', done: 'Unassigned' },
  decline_cancel: { label: 'Decline cancellation', kind: 'secondary', reason: 'Why can it not be cancelled?', done: 'Cancellation declined' },
  complete:       { label: 'Mark completed', kind: 'secondary', done: 'Marked as completed' },
  reject:         { label: 'Reject', kind: 'danger', reason: 'Why is this request rejected?', done: 'Request rejected' },
  cancel:         { label: 'Cancel request', kind: 'danger', confirm: 'This withdraws your request. It cannot be undone.', done: 'Request cancelled' },
  request_cancel: { label: 'Request cancellation', kind: 'danger', reason: 'Why do you need to cancel?', done: 'Cancellation requested' },
  confirm_cancel: { label: 'Confirm cancellation', kind: 'danger', confirm: 'The booking will be marked as cancelled and the employee notified.', done: 'Cancellation confirmed' },
}
const KIND_ORDER = { primary: 0, secondary: 1, danger: 2 }
export const sortActions = (list) =>
  [...list].sort((a, b) => KIND_ORDER[ACTIONS[a]?.kind ?? 1] - KIND_ORDER[ACTIONS[b]?.kind ?? 1])

export const EVENT_LABELS = {
  submit: 'submitted the request',
  resubmit: 'resubmitted the request',
  approve: 'approved',
  return: 'requested changes',
  reject: 'rejected',
  cancel: 'cancelled the request',
  request_cancel: 'asked to cancel',
  pick_up: 'started booking',
  assign: 'assigned the trip',
  release: 'released it to the queue',
  unavailable: 'marked it unavailable',
  book: 'finished booking the trip',
  book_leg: 'booked a ticket',
  confirm_cancel: 'confirmed the cancellation',
  decline_cancel: 'declined the cancellation',
  complete: 'marked it completed',
  expire: 'expired the request',
  reassign: 'reassigned the approver',
}

export const STEPS = ['Submitted', 'Manager approval', 'Travel desk', 'Booked', 'Completed']
// Which step is "current" for each status (5 = everything done).
export const STEP_OF = {
  PENDING_APPROVAL: 1, RETURNED: 1, APPROVED: 2, IN_PROGRESS: 2,
  BOOKED: 3, CANCELLATION_REQUESTED: 3, COMPLETED: 5,
}

// Travel profile choices (same values as the server)
export const GENDERS = [
  { value: 'FEMALE', label: 'Female' }, { value: 'MALE', label: 'Male' }, { value: 'OTHER', label: 'Other' },
]
export const SEATS = [
  { value: 'WINDOW', label: 'Window' }, { value: 'AISLE', label: 'Aisle' }, { value: 'ANY', label: 'No preference' },
]
export const MEALS = [
  { value: 'VEG', label: 'Vegetarian' }, { value: 'NON_VEG', label: 'Non-vegetarian' }, { value: 'JAIN', label: 'Jain' },
  { value: 'VEGAN', label: 'Vegan' }, { value: 'ANY', label: 'No preference' },
]

export const TRIP_TYPES = [
  { value: 'DOMESTIC', label: 'Domestic', text: 'Within India: flight, train, cab, hotel' },
  { value: 'INTERNATIONAL', label: 'International', text: 'Abroad: passport & visa taken from your profile' },
]

// Same list as the server (desk/countries.py): visas and trips must use identical country names.
export const COUNTRIES = [
  'Afghanistan', 'Albania', 'Algeria', 'Andorra', 'Angola', 'Antigua and Barbuda', 'Argentina', 'Armenia',
  'Australia', 'Austria', 'Azerbaijan', 'Bahamas', 'Bahrain', 'Bangladesh', 'Barbados', 'Belarus', 'Belgium',
  'Belize', 'Benin', 'Bhutan', 'Bolivia', 'Bosnia and Herzegovina', 'Botswana', 'Brazil', 'Brunei', 'Bulgaria',
  'Burkina Faso', 'Burundi', 'Cambodia', 'Cameroon', 'Canada', 'Cape Verde', 'Central African Republic', 'Chad',
  'Chile', 'China', 'Colombia', 'Comoros', 'Congo', 'Costa Rica', 'Croatia', 'Cuba', 'Cyprus', 'Czech Republic',
  'Democratic Republic of the Congo', 'Denmark', 'Djibouti', 'Dominica', 'Dominican Republic', 'Ecuador', 'Egypt',
  'El Salvador', 'Equatorial Guinea', 'Eritrea', 'Estonia', 'Eswatini', 'Ethiopia', 'Fiji', 'Finland', 'France',
  'Gabon', 'Gambia', 'Georgia', 'Germany', 'Ghana', 'Greece', 'Grenada', 'Guatemala', 'Guinea', 'Guinea-Bissau',
  'Guyana', 'Haiti', 'Honduras', 'Hong Kong', 'Hungary', 'Iceland', 'India', 'Indonesia', 'Iran', 'Iraq', 'Ireland',
  'Israel', 'Italy', 'Ivory Coast', 'Jamaica', 'Japan', 'Jordan', 'Kazakhstan', 'Kenya', 'Kiribati', 'Kuwait',
  'Kyrgyzstan', 'Laos', 'Latvia', 'Lebanon', 'Lesotho', 'Liberia', 'Libya', 'Liechtenstein', 'Lithuania',
  'Luxembourg', 'Macau', 'Madagascar', 'Malawi', 'Malaysia', 'Maldives', 'Mali', 'Malta', 'Marshall Islands',
  'Mauritania', 'Mauritius', 'Mexico', 'Micronesia', 'Moldova', 'Monaco', 'Mongolia', 'Montenegro', 'Morocco',
  'Mozambique', 'Myanmar', 'Namibia', 'Nauru', 'Nepal', 'Netherlands', 'New Zealand', 'Nicaragua', 'Niger',
  'Nigeria', 'North Korea', 'North Macedonia', 'Norway', 'Oman', 'Pakistan', 'Palau', 'Palestine', 'Panama',
  'Papua New Guinea', 'Paraguay', 'Peru', 'Philippines', 'Poland', 'Portugal', 'Qatar', 'Romania', 'Russia',
  'Rwanda', 'Saint Kitts and Nevis', 'Saint Lucia', 'Saint Vincent and the Grenadines', 'Samoa', 'San Marino',
  'Sao Tome and Principe', 'Saudi Arabia', 'Senegal', 'Serbia', 'Seychelles', 'Sierra Leone', 'Singapore',
  'Slovakia', 'Slovenia', 'Solomon Islands', 'Somalia', 'South Africa', 'South Korea', 'South Sudan', 'Spain',
  'Sri Lanka', 'Sudan', 'Suriname', 'Sweden', 'Switzerland', 'Syria', 'Taiwan', 'Tajikistan', 'Tanzania', 'Thailand',
  'Timor-Leste', 'Togo', 'Tonga', 'Trinidad and Tobago', 'Tunisia', 'Turkey', 'Turkmenistan', 'Tuvalu', 'Uganda',
  'Ukraine', 'United Arab Emirates', 'United Kingdom', 'United States', 'Uruguay', 'Uzbekistan', 'Vanuatu',
  'Vatican City', 'Venezuela', 'Vietnam', 'Yemen', 'Zambia', 'Zimbabwe',
]
