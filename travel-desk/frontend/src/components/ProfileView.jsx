// Read-only travel profile: the owner's "My profile", and what the Travel Desk / administrators see.
import { useEffect, useState } from 'react'
import { BookUser, Download, IdCard, Plane, User } from 'lucide-react'
import { api } from '../api.js'
import { formatDate } from '../utils.js'
import Modal from './Modal.jsx'
import { Alert, Avatar, Badge, Spinner } from './ui.jsx'

const dash = <span className="subtle">—</span>

export default function ProfileView({ profile: p }) {
  const passportExpired = p.has_passport && p.passport_expiry_date && p.passport_expiry_date < new Date().toISOString().slice(0, 10)
  return (
    <div className="profile-view">
      {!p.completed_at && <Alert>This profile has not been filled in yet.</Alert>}

      <Section icon={User} title="Basic information">
        <Item label="Name (as on ID)">{`${p.first_name} ${p.last_name}`.trim() || dash}</Item>
        <Item label="Date of birth">{p.date_of_birth ? formatDate(p.date_of_birth) : dash}</Item>
        <Item label="Gender">{p.gender_label || dash}</Item>
        <Item label="Mobile">{p.phone || dash}</Item>
        <Item label="Email">{p.email || dash}</Item>
        <Item label="Employee ID">{p.employee_id || dash}</Item>
        <Item label="Designation">{p.designation || dash}</Item>
        <Item label="Department">{p.department || dash}</Item>
        <Item label="Address" wide>{p.address || dash}</Item>
        <Item label="Emergency contact" wide>
          {p.emergency_contact_name ? `${p.emergency_contact_name} · ${p.emergency_contact_phone}` : dash}
        </Item>
      </Section>

      <Section icon={IdCard} title="Identity documents">
        <Item label="Aadhaar">{p.aadhaar_last4 ? `XXXX XXXX ${p.aadhaar_last4}` : dash} <Doc href={p.aadhaar_file} /></Item>
        <Item label="PAN">{p.pan_number || dash} <Doc href={p.pan_file} /></Item>
      </Section>

      <Section icon={BookUser} title="Passport & visas">
        {p.has_passport ? (
          <>
            <Item label="Passport number">{p.passport_number} <Doc href={p.passport_file} /></Item>
            <Item label="Place of issue">{p.passport_place_of_issue}</Item>
            <Item label="Issued">{formatDate(p.passport_issue_date)}</Item>
            <Item label="Valid until">
              {formatDate(p.passport_expiry_date)} {passportExpired && <Badge tone="red">Expired</Badge>}
            </Item>
            <Item label="Visas" wide>
              {p.visas.length ? (
                <ul className="plain-list">
                  {p.visas.map((v) => (
                    <li key={v.id}><strong>{v.country}</strong> · {v.visa_type} · valid until {formatDate(v.expiry_date)} <Doc href={v.file} /></li>
                  ))}
                </ul>
              ) : 'None'}
            </Item>
          </>
        ) : <Item label="Passport" wide>No passport</Item>}
      </Section>

      <Section icon={Plane} title="Travel preferences">
        <Item label="Seat">{p.seat_preference_label || dash}</Item>
        <Item label="Meal">{p.meal_preference_label || dash}</Item>
        <Item label="Frequent flyer" wide>
          {p.has_frequent_flyer && p.frequent_flyers.length
            ? p.frequent_flyers.map((f) => `${f.airline}: ${f.membership_number}`).join(' · ')
            : 'None'}
        </Item>
        <Item label="Forex card" wide>{p.has_forex_card ? `${p.forex_bank} · card ending ${p.forex_card_last4}` : 'None'}</Item>
      </Section>
    </div>
  )
}

function Section({ icon: Icon, title, children }) {
  return (
    <section className="profile-section">
      <p className="section-label"><Icon size={14} /> {title}</p>
      <dl className="details">{children}</dl>
    </section>
  )
}

function Item({ label, wide, children }) {
  return (
    <div className={`detail ${wide ? 'wide' : ''}`}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function Doc({ href }) {
  return href ? <a className="link-btn doc-link" href={href}><Download size={13} /> Copy</a> : null
}

/** Someone else's profile, for the Travel Desk (from a request) and administrators (from Employees). */
export function ProfileDialog({ userId, onClose }) {
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { api(`/profiles/${userId}/`).then(setProfile).catch((e) => setError(e.message)) }, [userId])

  const name = profile ? `${profile.first_name} ${profile.last_name}`.trim() || profile.username : ''
  const header = profile && (
    <div className="account-head">
      <Avatar name={name} size={44} />
      <div>
        <h2>{name}</h2>
        <p className="subtle">{[profile.designation, profile.department].filter(Boolean).join(' · ') || profile.role_label}</p>
        <p className="subtle xs">@{profile.username}{profile.updated_at && ` · profile updated ${formatDate(profile.updated_at)}`}</p>
      </div>
    </div>
  )
  return (
    <Modal header={header} title={profile ? undefined : 'Traveller profile'} onClose={onClose} size="wide" dismissible>
      <Alert>{error}</Alert>
      {!profile && !error && <div className="center"><Spinner size={22} /></div>}
      {profile && <ProfileView profile={profile} />}
      {profile && <p className="subtle xs">Personal details are visible only to the person, the Travel Desk and administrators.</p>}
    </Modal>
  )
}
