import React, { useCallback, useEffect, useState } from 'react'
import { Download, GitBranch, Sparkles, Trash2 } from 'lucide-react'
import { api, WorkspaceStatus, WorktreeInspect } from '../api'
import { ConfirmButton } from './ConfirmButton'

interface WorktreePanelProps {
  status: WorkspaceStatus | null
  /** Called after something was removed, so the inspector and Console can reload. */
  onChanged: () => void
}

/* What each isolated worktree holds against the branch it came from, and the three safe things to do with it: read it,
   export it as a patch (your branch is never touched), or tidy it away once everything in it is already in the base. */
export const WorktreePanel: React.FC<WorktreePanelProps> = ({ status, onChanged }) => {
  const keys = (status?.worktrees ?? []).map((w) => w.key)
  const integrated = status?.integrated_worktrees ?? []
  const [info, setInfo] = useState<Record<string, WorktreeInspect | { error: string }>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const keyList = keys.join('|')

  const load = useCallback(async () => {
    const entries = await Promise.all(keys.map(async (k) => {
      try { return [k, await api.inspectWorktree(k)] as const } catch (e: any) { return [k, { error: e.message || 'No se pudo inspeccionar' }] as const }
    }))
    setInfo(Object.fromEntries(entries))
  }, [keyList]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load() }, [load])

  const exportPatch = async (key?: string) => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.exportPatch(key)
      setMsg(`Parche listo: ${r.filename} · ${r.files} archivo(s)`)
      window.location.assign(api.downloadUrl(r.filename))
    } catch (e: any) {
      setMsg(e.message || 'No se pudo exportar')
    } finally {
      setBusy(false)
    }
  }
  const cleanup = async () => {
    setBusy(true)
    try {
      const r = await api.cleanupWorktrees()
      setMsg(r.removed.length ? `Limpiados: ${r.removed.join(', ')}` : 'No había nada integrado que limpiar')
      onChanged()
    } catch (e: any) {
      setMsg(e.message || 'No se pudo limpiar')
    } finally {
      setBusy(false)
    }
  }
  const discard = async (key: string) => {
    setBusy(true)
    try {
      await api.discardWorktree(key)
      onChanged()
    } catch (e: any) {
      setMsg(e.message || 'No se pudo descartar')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="wt-panel">
      <p className="muted wt-lead">Los cambios aislados nunca se fusionan solos en tu rama: se leen, se exportan como parche o se descartan.</p>
      <div className="wt-actions">
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => exportPatch()} title="Cambios sin confirmar del proyecto, como .patch">
          <Download className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />Parche del proyecto
        </button>
        <button type="button" className="btn btn-sm" disabled={busy || integrated.length === 0} onClick={cleanup} title="Quita los worktrees limpios cuyos commits ya están en la rama base">
          <Sparkles className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />Limpiar integrados ({integrated.length})
        </button>
      </div>
      {msg && <p className="mono wt-msg" role="status">{msg}</p>}
      {keys.length === 0 && <p className="mono muted">No hay worktrees aislados. Activa «Worktree» en Console antes de enviar un mensaje en Act.</p>}
      <ul className="wt-list">
        {keys.map((k) => {
          const d = info[k]
          const ok = d && !('error' in d) ? d : null
          return (
            <li key={k} className="wt-item">
              <div className="wt-item-head">
                <GitBranch className="icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
                <b className="mono">{ok?.branch ?? k}</b>
                {ok && <span className="chip">{ok.integrated ? 'integrado' : ok.dirty > 0 ? `${ok.dirty} sin confirmar` : `${ok.ahead} commit(s) por delante`}</span>}
              </div>
              {d && 'error' in d && <p className="verdict-err">{d.error}</p>}
              {ok && (
                <>
                  <p className="mono muted wt-sub">base {ok.base} · adelante {ok.ahead} · atrás {ok.behind}</p>
                  <ul className="wt-files">
                    {ok.files.slice(0, 6).map((f) => (
                      <li key={f.path}><span className="mono f-path" title={f.path}>{f.path}</span><span className="mono f-delta">{f.added > 0 && <b className="plus">+{f.added}</b>}{f.removed > 0 && <b className="minus">-{f.removed}</b>}{!f.committed && <i className="muted">sin confirmar</i>}</span></li>
                    ))}
                    {ok.files.length > 6 && <li className="mono muted">… y {ok.files.length - 6} más</li>}
                  </ul>
                </>
              )}
              <div className="wt-actions">
                <button type="button" className="btn btn-sm" disabled={busy} onClick={() => exportPatch(k)}><Download className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />Exportar .patch</button>
                <ConfirmButton className="btn btn-quiet btn-sm" disabled={busy} question={`¿Descartar ${k}? Su trabajo sin confirmar se pierde.`} confirmLabel="Descartar" onConfirm={() => discard(k)}>
                  <Trash2 className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />Descartar
                </ConfirmButton>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
