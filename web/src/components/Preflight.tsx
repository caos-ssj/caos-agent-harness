import React from 'react'
import { AlertTriangle, CheckCircle2, CircleDot, KeyRound, RefreshCw, ShieldX, X } from '../icons'
import { PreflightCheck, PreflightResponse } from '../api'
import { useDialog, usePresence } from '../hooks'

const VERDICT: Record<PreflightResponse['verdict'], { label: string; cls: string; Icon: React.ElementType }> = {
  ready: { label: 'Listo', cls: 'pass', Icon: CheckCircle2 },
  warning: { label: 'Con avisos', cls: 'act', Icon: AlertTriangle },
  blocked: { label: 'Bloqueado', cls: 'fail', Icon: ShieldX },
}
const LEVEL_ICON: Record<PreflightCheck['level'], { Icon: React.ElementType; cls: string }> = {
  ok: { Icon: CheckCircle2, cls: 'pass' },
  info: { Icon: CircleDot, cls: 'mute' },
  warning: { Icon: AlertTriangle, cls: 'act' },
  blocked: { Icon: ShieldX, cls: 'fail' },
}
const needsKey = (c: PreflightCheck) => ['cloud', 'agents', 'engine', 'failover'].includes(c.id) && c.level !== 'ok' && c.level !== 'info'

export const VerdictBadge: React.FC<{ verdict: PreflightResponse['verdict'] }> = ({ verdict }) => {
  const v = VERDICT[verdict]
  return <span className={`verdict-badge ${v.cls}`}><v.Icon className="icon" style={{ width: 13, height: 13 }} aria-hidden="true" />{v.label}</span>
}

interface DrawerProps {
  open: boolean
  data: PreflightResponse | null
  loading: boolean
  onClose: () => void
  onRecheck: () => void
  onGoProviders: () => void
}

export const PreflightDrawer: React.FC<DrawerProps> = ({ open, data, loading, onClose, onRecheck, onGoProviders }) => {
  const pres = usePresence(open, 160)
  const ref = useDialog<HTMLElement>(open, onClose, { initial: 'button' })
  if (!pres.mounted) return null
  return (
    <aside className="preflight-drawer" ref={ref} data-leaving={pres.leaving ? '' : undefined} role="dialog" aria-label="Preflight del entorno">
      <header>
        <h2>Preflight</h2>
        {data && <VerdictBadge verdict={data.verdict} />}
        <span className="spacer" />
        <button type="button" className="btn btn-quiet btn-sm btn-icon" aria-label="Volver a comprobar" title="Volver a comprobar (con sondeos de red)" disabled={loading} onClick={onRecheck}><RefreshCw className={`icon ${loading ? 'spin' : ''}`} style={{ width: 15, height: 15 }} aria-hidden="true" /></button>
        <button type="button" className="btn btn-quiet btn-sm btn-icon" aria-label="Cerrar" onClick={onClose}><X className="icon" style={{ width: 15, height: 15 }} aria-hidden="true" /></button>
      </header>
      {!data && <p className="muted mono">{loading ? 'Comprobando…' : 'Sin datos.'}</p>}
      {data && (
        <>
          <p className="muted mono preflight-meta">{data.dry_run ? 'modo seco, sin red' : 'con sondeos de Ollama'} · {data.tokens_spent} tokens gastados</p>
          <ul className="preflight-list">
            {data.checks.map((c) => {
              const L = LEVEL_ICON[c.level]
              return (
                <li key={c.id} className={`lvl-${c.level}`}>
                  <L.Icon className={`icon ${L.cls}`} style={{ width: 15, height: 15 }} aria-hidden="true" />
                  <div><b>{c.label}</b><small>{c.detail}</small>{c.action && c.level !== 'ok' && <small className="preflight-action">{c.action}</small>}</div>
                  {needsKey(c) && <button type="button" className="btn btn-xs" onClick={() => { onClose(); onGoProviders() }}><KeyRound className="icon" style={{ width: 12, height: 12 }} aria-hidden="true" />Key</button>}
                </li>
              )
            })}
          </ul>
          {data.next_actions.length > 0 && (
            <div className="preflight-next"><h3>Siguiente</h3><ol>{data.next_actions.map((a) => <li key={a}><code>{a}</code></li>)}</ol></div>
          )}
        </>
      )}
    </aside>
  )
}
