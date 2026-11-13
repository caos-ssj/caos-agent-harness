import React, { useState } from 'react'
import { ChevronRight } from '../icons'

interface AccordionProps {
  id: string
  title: string
  count?: number | string
  badge?: React.ReactNode
  defaultOpen?: boolean
  accent?: string
  children: React.ReactNode
}

/** Persisted collapsible section used to eliminate dead scroll across every view. */
export const Accordion: React.FC<AccordionProps> = ({
  id,
  title,
  count,
  badge,
  defaultOpen = false,
  accent,
  children,
}) => {
  const key = `caos_acc_${id}`
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem(key)
      if (saved === '1') return true
      if (saved === '0') return false
    } catch {
      /* ignore */
    }
    return defaultOpen
  })

  const onToggle = (e: React.SyntheticEvent<HTMLDetailsElement>) => {
    const next = e.currentTarget.open
    setOpen(next)
    try {
      localStorage.setItem(key, next ? '1' : '0')
    } catch {
      /* ignore */
    }
  }

  return (
    <details
      className="acc"
      open={open}
      onToggle={onToggle}
      style={accent ? ({ '--acc-accent': accent } as React.CSSProperties) : undefined}
    >
      <summary className="acc-head">
        <ChevronRight className="icon acc-chev" aria-hidden="true" />
        <span className="acc-title">{title}</span>
        {count !== undefined && <span className="acc-count">{count}</span>}
        {badge && <span className="acc-badge">{badge}</span>}
      </summary>
      <div className="acc-body">{children}</div>
    </details>
  )
}
