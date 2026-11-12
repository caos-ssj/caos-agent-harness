import React, { useEffect, useRef, useState } from 'react'

interface ConfirmButtonProps {
  /** What the trigger button shows. */
  children: React.ReactNode
  /** The question asked once it is pressed, e.g. "Delete this session?". */
  question: string
  confirmLabel: string
  onConfirm: () => void
  className?: string
  ariaLabel?: string
  title?: string
  disabled?: boolean
}

/* A destructive action asks inside the page, next to where it was pressed: the first press turns the button into
   "question · Cancel · Confirm" with focus on Cancel, Escape or a click elsewhere backs out. Nothing native pops up. */
export const ConfirmButton: React.FC<ConfirmButtonProps> = ({ children, question, confirmLabel, onConfirm, className = 'btn btn-quiet btn-sm', ariaLabel, title, disabled }) => {
  const [armed, setArmed] = useState(false)
  const box = useRef<HTMLSpanElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const wasArmed = useRef(false)

  useEffect(() => {
    if (armed) {
      box.current?.querySelector<HTMLElement>('[data-cancel]')?.focus()
      const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setArmed(false) } }
      const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setArmed(false) }
      document.addEventListener('keydown', key, true); document.addEventListener('mousedown', away)
      wasArmed.current = true
      return () => { document.removeEventListener('keydown', key, true); document.removeEventListener('mousedown', away) }
    }
    if (wasArmed.current) { wasArmed.current = false; trigger.current?.focus() }
  }, [armed])

  if (!armed) {
    return <button ref={trigger} type="button" className={className} aria-label={ariaLabel} title={title} disabled={disabled} onClick={() => setArmed(true)}>{children}</button>
  }
  return (
    <span ref={box} className="confirm" role="group" aria-label={question}>
      <span className="confirm-q">{question}</span>
      <button type="button" className="btn btn-sm" data-cancel onClick={() => setArmed(false)}>Cancel</button>
      <button type="button" className="btn btn-sm btn-danger" onClick={() => { setArmed(false); onConfirm() }}>{confirmLabel}</button>
    </span>
  )
}
