import React, { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, FolderGit2, FolderPlus, X } from 'lucide-react'
import { api, Workspace } from '../api'

interface WorkspaceMenuProps { project: string; root?: string; onSwitched: () => void }

/* Switch between project folders. Only folders the operator listed can be opened, and adding one checks that it is
   a real folder with a harness.toml (or creates one, when asked). Each folder keeps its own board and sessions in
   its own .harness/ directory. */
export const WorkspaceMenu: React.FC<WorkspaceMenuProps> = ({ project, root, onSwitched }) => {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<Workspace[]>([])
  const [path, setPath] = useState('')
  const [init, setInit] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  const load = () => api.getWorkspaces().then((r) => { setItems(r.items); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { if (open) load() }, [open])
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const click = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('keydown', key); window.addEventListener('mousedown', click)
    return () => { window.removeEventListener('keydown', key); window.removeEventListener('mousedown', click) }
  }, [open])

  const run = async (fn: () => Promise<unknown>, done?: () => void) => {
    setBusy(true); setError(null)
    try { await fn(); await load(); done?.() } catch (e: any) { setError(e.message || 'That did not work.') } finally { setBusy(false) }
  }
  const switchTo = (w: Workspace) => run(() => api.switchWorkspace(w.path), () => { setOpen(false); onSwitched() })
  const add = (e: React.FormEvent) => { e.preventDefault(); if (path.trim()) run(() => api.addWorkspace(path.trim(), init), () => { setPath(''); setInit(false) }) }

  return (
    <div className="ws" ref={box}>
      <button type="button" className="repo-chip" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen(!open)} title={root || 'Workspace'}>
        <FolderGit2 className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" />
        <b>{project || '…'}</b>
        <ChevronDown className="icon" style={{ width: 14, height: 14, transform: open ? 'rotate(180deg)' : 'none' }} aria-hidden="true" />
      </button>
      {open && (
        <div className="pop ws-pop" role="dialog" aria-label="Workspaces">
          <img className="pop-plate" src="/art/workspace.svg" alt="" aria-hidden="true" />
          <h2>Workspaces</h2>
          <p className="hint" style={{ margin: '-8px 0 12px', paddingRight: 70 }}>Each folder has its own board, traces and sessions. Shell commands start off again when you switch.</p>
          <ul className="ws-list">
            {items.map((w) => (
              <li key={w.path} className={w.current ? 'current' : ''}>
                <button type="button" className="ws-item" disabled={busy || w.current || !w.ready} onClick={() => switchTo(w)} aria-current={w.current ? 'true' : undefined}>
                  <span className="ws-mark">{w.current ? <Check className="icon" aria-hidden="true" /> : <FolderGit2 className="icon" aria-hidden="true" />}</span>
                  <span className="ws-text"><b>{w.name}</b><small title={w.path}>{w.ready ? w.path : `${w.path} · no harness.toml`}</small></span>
                </button>
                {!w.current && <button type="button" className="btn btn-quiet btn-sm btn-icon" aria-label={`Remove ${w.name} from the list`} title="Remove from the list (the folder is not touched)" disabled={busy} onClick={() => run(() => api.removeWorkspace(w.path))}><X className="icon" aria-hidden="true" /></button>}
              </li>
            ))}
          </ul>
          <form onSubmit={add} className="ws-add">
            <label htmlFor="ws-path">Add a folder</label>
            <div className="ws-row">
              <input id="ws-path" className="field" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/absolute/path/to/the/folder" spellCheck={false} />
              <button type="submit" className="btn btn-sm" disabled={busy || !path.trim()}><FolderPlus className="icon" aria-hidden="true" />Add</button>
            </div>
            <label className="ws-check"><input type="checkbox" checked={init} onChange={(e) => setInit(e.target.checked)} />Create harness.toml there if it has none</label>
          </form>
          {error && <p className="verdict-err" role="alert" style={{ marginTop: 10 }}>{error}</p>}
        </div>
      )}
    </div>
  )
}
