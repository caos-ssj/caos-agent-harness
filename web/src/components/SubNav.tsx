import React from 'react'
import { Activity, Cpu, Share2, Wrench } from '../icons'
import { View, onTabKeys } from '../lib'
import { GROUPS } from './Header'

const SUB: Partial<Record<View, { label: string; Icon: React.ElementType }>> = {
  skills: { label: 'Skills & Tools', Icon: Wrench },
  share: { label: 'Share / Team', Icon: Share2 },
  providers: { label: 'Models & Providers', Icon: Cpu },
  metrics: { label: 'Metrics', Icon: Activity },
}

/* The second row of Team and System: one click between the views of the group, no hunting. Console and Board have none. */
export const SubNav: React.FC<{ view: View; onView: (v: View) => void }> = ({ view, onView }) => {
  const group = GROUPS.find((g) => g.views.includes(view))
  if (!group || group.views.length < 2) return null
  return (
    <nav className="subnav" role="tablist" aria-label={`${group.label} sections`} onKeyDown={onTabKeys}>
      {group.views.map((v) => {
        const { label, Icon } = SUB[v]!
        return (
          <button key={v} type="button" role="tab" aria-selected={view === v} tabIndex={view === v ? 0 : -1} data-tab={v} onClick={() => onView(v)}>
            <Icon className="icon" aria-hidden="true" />{label}
          </button>
        )
      })}
    </nav>
  )
}
