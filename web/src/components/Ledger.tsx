import React from 'react'
import { StateResponse } from '../api'
import { NEEDS, fmt } from '../lib'

interface LedgerProps { state: StateResponse | null; onNeeds: () => void }

/* The figures as one line. Each one says where it comes from; none is computed from anything but the board's own
   aggregates (`Board.stats()`), the task list the server returned, or a report a command wrote. */
export const Ledger: React.FC<LedgerProps> = ({ state, onNeeds }) => {
  const s = state?.stats
  const tasks = state?.tasks ?? []
  const needs = tasks.filter((t) => NEEDS.has(t.state)).length
  const runnable = tasks.filter((t) => t.state === 'pending' && t.queue !== 'person').length
  const withPerson = tasks.filter((t) => t.state === 'person').length
  const accepted = s?.review?.ok ?? 0
  const m = state?.quality?.mutation
  return (
    <div className="ledger" role="group" aria-label="Figures from this board">
      <button type="button" className={`ledger-cell ${needs ? 'due' : 'gone'}`} onClick={onNeeds}>
        <span className="ledger-label">Waiting for you</span>
        <span className="ledger-value">{needs}<small>to review or decide</small></span>
        <span className="ledger-source">board</span>
      </button>
      <div className="ledger-cell">
        <span className="ledger-label">On the board</span>
        <span className="ledger-value">{fmt(s?.tasks ?? 0)}<small>{runnable} ready to run{withPerson ? ` · ${withPerson} with a person` : ''}</small></span>
        <span className="ledger-source">caos-harness status</span>
      </div>
      <div className="ledger-cell">
        <span className="ledger-label">Accepted</span>
        <span className="ledger-value">{fmt(accepted)}<small>{s?.returned_at_least_once ?? 0} returned once</small></span>
        <span className="ledger-source">caos-harness status</span>
      </div>
      <div className="ledger-cell">
        <span className="ledger-label">Faults caught</span>
        <span className="ledger-value">{m ? `${m.caught}/${m.total}` : '—'}<small>{m ? 'injected' : 'no report yet'}</small></span>
        <span className="ledger-source">{m ? m.source : 'run make mutation'}</span>
      </div>
      {state?.running && <span className="run-line" role="progressbar" aria-label="A run is in progress" />}
    </div>
  )
}
