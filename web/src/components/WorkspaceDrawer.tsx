import React, { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { api, WorkspaceStatus } from '../api'

interface WorkspaceDrawerProps { isOpen: boolean; onClose: () => void; activeRepo: string; onTaskCreated?: () => void }

/* Read-only: where the console works. The folder, its git branch, what is uncommitted, and the skills it can read. */
export const WorkspaceDrawer: React.FC<WorkspaceDrawerProps> = ({ isOpen, onClose, activeRepo }) => {
  const [status, setStatus] = useState<WorkspaceStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { if (isOpen) api.getWorkspaceStatus().then((s) => { setStatus(s); setError(null) }).catch((e) => setError(e.message)) }, [isOpen, activeRepo])
  if (!isOpen) return null
  const h = { margin: '18px 0 6px', font: '500 18px var(--serif)', color: 'var(--ink-2)' } as React.CSSProperties
  return (
    <aside className="ctx" aria-label="Project context">
      <div className="ctx-head"><h2>Project context</h2><button type="button" className="btn btn-quiet btn-sm btn-icon" onClick={onClose} aria-label="Close the context"><X className="icon" aria-hidden="true" /></button></div>
      <div className="scroll" style={{ padding: '0 16px 18px' }}>
        {error && <p className="verdict-err">{error}</p>}
        {!status && !error && <p style={{ color: 'var(--ink-2)' }}>Reading the folder…</p>}
        {status && (
          <>
            <h3 style={{ ...h, marginTop: 6 }}>Folder</h3>
            <p className="mono" style={{ margin: 0 }}>{status.repo}</p>
            <p className="mono" style={{ margin: '2px 0 0', color: 'var(--ink-3)' }}>branch {status.branch}</p>
            <h3 style={h}>Uncommitted files · {status.dirty_files.length}</h3>
            {status.dirty_files.length === 0 ? <p className="mono" style={{ margin: 0, color: 'var(--ink-3)' }}>The working tree is clean.</p>
              : <ul className="mono" style={{ margin: 0, padding: 0, listStyle: 'none', color: 'var(--ink-2)', maxHeight: 220, overflow: 'auto' }}>{status.dirty_files.map((f, i) => <li key={i} style={{ padding: '2px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f}</li>)}</ul>}
            <h3 style={h}>Skills it can read · {status.skills.length}</h3>
            <div className="chips">{status.skills.map((s) => <span key={s} className="chip">{s}</span>)}</div>
          </>
        )}
      </div>
    </aside>
  )
}
