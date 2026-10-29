// Shown once after registering someone or resetting their password.
// The temporary password is never stored in plain text, so it can't be shown again later.
import { useState } from 'react'
import { Check, CircleCheck, Copy, Eye, EyeOff, MailCheck, MailWarning } from 'lucide-react'
import Modal from './Modal.jsx'
import { Banner, Button } from './ui.jsx'

export default function CredentialsDialog({ title, person, result, onClose, onAnother }) {
  const [show, setShow] = useState(false)
  const [copied, setCopied] = useState('')

  async function copy(label, text) {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(label)
      setTimeout(() => setCopied(''), 1500)
    } catch { /* clipboard blocked: the value is still readable on screen */ }
  }

  function Row({ label, value, secret }) {
    return (
      <div className="cred-row">
        <span className="subtle">{label}</span>
        <code>{secret && !show ? '•'.repeat(value.length) : value}</code>
        {secret && (
          <button className="icon-btn sm" onClick={() => setShow(!show)} aria-label={show ? 'Hide' : 'Show'}>
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
        <button className="icon-btn sm" onClick={() => copy(label, value)} aria-label={`Copy ${label}`}>
          {copied === label ? <Check size={14} /> : <Copy size={14} />}
        </button>
      </div>
    )
  }

  return (
    <Modal size="small" onClose={onClose} bodyClassName="cred-body"
           footer={<>
             {onAnother && <Button onClick={onAnother}>Register another</Button>}
             <Button kind="primary" onClick={onClose}>Done</Button>
           </>}>
      <div className="cred-head"><CircleCheck size={28} /><h2>{title}</h2></div>
      <p className="subtle">{person.full_name}{person.designation && ` · ${person.designation}`}</p>

      <div className="cred-box">
        <Row label="Username" value={person.username} />
        <Row label="Temporary password" value={result.temporary_password} secret />
      </div>

      {result.email_sent ? (
        <Banner tone="green" icon={MailCheck} title={`Emailed to ${person.email}`}>
          They must choose their own password at first sign-in.
        </Banner>
      ) : (
        <Banner tone="orange" icon={MailWarning} title="Not emailed">
          {result.email_error || 'Share these details with them privately.'} They must choose their own password at first sign-in.
        </Banner>
      )}
      <p className="subtle xs">For security this password is shown only now. If it's lost, use "Reset password".</p>
    </Modal>
  )
}
