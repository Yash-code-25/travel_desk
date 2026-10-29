// Every pop-up window in the app is built from <Modal>.
import { X } from 'lucide-react'
import { useEscape } from '../hooks.js'
import { Button } from './ui.jsx'

/**
 * title / subtitle  – header text (or pass `header` for a custom header)
 * footer            – buttons at the bottom
 * onSubmit          – makes the whole modal a <form>
 * size              – '' (normal) | 'wide' | 'small'
 * dismissible       – close on Esc and on a click outside (off for forms, so typing is never lost)
 */
export default function Modal({
  title, subtitle, header, footer, onClose, onSubmit, size = '', dismissible = false,
  role = 'dialog', bodyClassName = '', children,
}) {
  useEscape(onClose, dismissible)
  const Tag = onSubmit ? 'form' : 'div'

  return (
    <div className="modal-layer" onClick={dismissible ? onClose : undefined}>
      <Tag className={`modal ${size}`} role={role} aria-modal="true" aria-label={typeof title === 'string' ? title : undefined}
           onClick={(e) => e.stopPropagation()} onSubmit={onSubmit} noValidate={onSubmit ? true : undefined}>
        {(title || header) && (
          <header className="modal-head">
            {header || (
              <div>
                <h2>{title}</h2>
                {subtitle && <p className="subtle">{subtitle}</p>}
              </div>
            )}
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X size={20} /></button>
          </header>
        )}
        <div className={`modal-body ${bodyClassName}`}>{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </Tag>
    </div>
  )
}

/** "Are you sure?" box. */
export function ConfirmDialog({ title, text, confirmLabel, danger, busy, onConfirm, onCancel }) {
  return (
    <Modal size="small" role="alertdialog" dismissible onClose={onCancel}
           footer={<>
             <Button onClick={onCancel}>Cancel</Button>
             <Button kind={danger ? 'danger' : 'primary'} loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
           </>}>
      <h2 className="confirm-title-lg">{title}</h2>
      <p className="subtle">{text}</p>
    </Modal>
  )
}
