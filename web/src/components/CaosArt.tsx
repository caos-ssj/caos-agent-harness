import React, { useId } from 'react'
import { ProviderItem, RouterResponse, StateResponse, WorkspaceStatus } from '../api'
import { View, boardCounts } from '../lib'
import { Cpu, Eye, ListChecks, Pencil as PencilSimple, ShieldCheck } from '../icons'

/* Custom CAOS hairline marks and live schematic representation.
   Every visual element reflects real harness state. Bone and silver are the steady machinery; the warm amber (#C9975C) is used ONLY where a
   human has to act or decide, so it is never part of a decorative glyph. */

export type SkillCategory = 'code' | 'models' | 'content' | 'research' | 'markets' | 'other'
const CATEGORY_LABEL: Record<SkillCategory, string> = { code: 'code & quality', models: 'models', content: 'writing & content', research: 'research', markets: 'markets', other: 'other' }
type SkillKind = 'code' | 'qa' | 'models' | 'proposal' | 'social' | 'research' | 'writer' | 'trading' | 'other'

/** The family a skill belongs to, by its name: English packaged names and the Spanish ones from the vault both land in the same family. */
function skillKind(name: string): SkillKind {
  const k = name.toLowerCase()
  if (/(^|[-_])(qa|test|tests|valid\w*)([-_]|$)/.test(k)) return 'qa'
  if (/coder|codigo|código|\bcode\b|agente-codigo/.test(k)) return 'code'
  if (/model|modelos|selection|router|ollama/.test(k)) return 'models'
  if (/propos|propuesta|cotiz|quote/.test(k)) return 'proposal'
  if (/social|contenido|content|reel|post/.test(k)) return 'social'
  if (/research|investig|source|fuente/.test(k)) return 'research'
  if (/writer|redact|writing|docs?\b/.test(k)) return 'writer'
  if (/trading|acciones|market|bolsa/.test(k)) return 'trading'
  return 'other'
}
export function skillCategory(name: string): { id: SkillCategory; label: string } {
  const kind = skillKind(name)
  const id: SkillCategory = kind === 'code' || kind === 'qa' ? 'code' : kind === 'models' ? 'models' : kind === 'proposal' || kind === 'social' || kind === 'writer' ? 'content' : kind === 'research' ? 'research' : kind === 'trading' ? 'markets' : 'other'
  return { id, label: CATEGORY_LABEL[id] }
}

const hash = (s: string) => { let h = 2166136261; for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0 }

/** A skill with no family of its own still gets a mark of its own: a hexagon whose inner spokes follow its name. */
const OtherGlyph: React.FC<{ name: string }> = ({ name }) => {
  const h = hash(name)
  const spokes = 2 + (h % 4)
  const turn = (h >> 3) % 60
  const pts = Array.from({ length: spokes }, (_, i) => { const a = ((360 / spokes) * i + turn) * (Math.PI / 180); return [14 + Math.cos(a) * 6, 14 + Math.sin(a) * 6] })
  return (
    <>
      <polygon points="14,3 23,8.5 23,19.5 14,25 5,19.5 5,8.5" stroke="var(--ink)" strokeWidth="1.4" />
      <circle cx="14" cy="14" r="1.6" fill="var(--ink)" />
      {pts.map(([x, y], i) => <path key={i} d={`M14 14L${x.toFixed(2)} ${y.toFixed(2)}`} stroke="var(--ink-2)" strokeWidth="1.3" />)}
    </>
  )
}

export const CaosSkillGlyph: React.FC<{ name: string; size?: number; local?: boolean }> = ({ name, size = 24, local = false }) => {
  const kind = skillKind(name)
  const svg = { width: size, height: size, viewBox: '0 0 28 28', fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const }
  let body: React.ReactNode
  switch (kind) {
    case 'code':
      body = (<><rect x="3" y="4" width="22" height="20" rx="4" stroke="var(--ink-3)" strokeWidth="1.2" /><path d="M10 11L7 14l3 3M18 11l3 3-3 3M15 9.5L13 18.5" stroke="var(--ink)" strokeWidth="1.5" /></>)
      break
    case 'qa':
      body = (<><circle cx="14" cy="14" r="10" stroke="var(--ink-3)" strokeWidth="1.1" strokeDasharray="2 2.5" /><circle cx="14" cy="14" r="6.5" stroke="var(--ink)" strokeWidth="1.35" /><path d="M11.2 14.2l2 2 4-4.2" stroke="var(--ink)" strokeWidth="1.6" /></>)
      break
    case 'models':   /* one request in, three engines out, one of them chosen */
      body = (<><circle cx="5" cy="14" r="2" stroke="var(--ink)" strokeWidth="1.4" /><path d="M7 14h4M11 14l4-7h4M11 14h8M11 14l4 7h4" stroke="var(--ink-3)" strokeWidth="1.2" />
        <rect x="19.5" y="4.5" width="5" height="5" rx="1.3" stroke="var(--ink-3)" strokeWidth="1.2" /><rect x="19.5" y="11.5" width="5" height="5" rx="1.3" fill="var(--ink)" stroke="var(--ink)" strokeWidth="1.2" /><rect x="19.5" y="18.5" width="5" height="5" rx="1.3" stroke="var(--ink-3)" strokeWidth="1.2" /></>)
      break
    case 'proposal':
      body = (<><path d="M6 4h11l5 5v15H6z" stroke="var(--ink)" strokeWidth="1.4" /><path d="M17 4v5h5" stroke="var(--ink-3)" strokeWidth="1.2" /><path d="M9.5 13h9M9.5 16.5h5" stroke="var(--ink-2)" strokeWidth="1.2" /><circle cx="17.5" cy="20" r="2.2" stroke="var(--ink-2)" strokeWidth="1.3" /></>)
      break
    case 'social':   /* a megaphone and its signal: something published, not a video */
      body = (<><path d="M5 11.5h4l8-4.5v14l-8-4.5H5z" stroke="var(--ink)" strokeWidth="1.45" /><path d="M9.5 16.5l1.4 5.5h3l-1.4-4.6" stroke="var(--ink-2)" strokeWidth="1.25" /><path d="M20 10.5a5 5 0 0 1 0 7M23 8a8.6 8.6 0 0 1 0 12" stroke="var(--ink-3)" strokeWidth="1.25" /></>)
      break
    case 'research':
      body = (<><circle cx="12.5" cy="12.5" r="7.5" stroke="var(--ink)" strokeWidth="1.45" /><circle cx="12.5" cy="12.5" r="3" stroke="var(--ink-3)" strokeWidth="1.1" /><path d="M18.2 18.2l6 6" stroke="var(--ink)" strokeWidth="1.65" /><path d="M12.5 3v2M12.5 20v2M3 12.5h2" stroke="var(--ink-3)" strokeWidth="1.1" /></>)
      break
    case 'writer':
      body = (<><path d="M5 23h18" stroke="var(--ink-3)" strokeWidth="1.2" /><path d="M19.5 5.5l3 3L11.5 19.5 7 21l1.5-4.5z" stroke="var(--ink)" strokeWidth="1.45" /><path d="M16.5 8.5l3 3" stroke="var(--ink-2)" strokeWidth="1.2" /></>)
      break
    case 'trading':  /* three candles */
      body = (<><path d="M7 5v18M14 4v17M21 8v16" stroke="var(--ink-3)" strokeWidth="1.2" /><rect x="5" y="9" width="4" height="8" rx="1" stroke="var(--ink)" strokeWidth="1.35" /><rect x="12" y="7" width="4" height="9" rx="1" fill="var(--ink)" stroke="var(--ink)" strokeWidth="1.35" /><rect x="19" y="12" width="4" height="7" rx="1" stroke="var(--ink)" strokeWidth="1.35" /></>)
      break
    default:
      body = <OtherGlyph name={name} />
  }
  return (
    <svg {...svg}>
      {local && <rect x="0.75" y="0.75" width="26.5" height="26.5" rx="7.5" stroke="var(--ink-3)" strokeWidth="0.9" strokeDasharray="2 2.6" />}
      {body}
    </svg>
  )
}

export const CaosTargetGlyph: React.FC<{ kind: 'model' | 'agent' | 'tier' | 'worktree'; size?: number }> = ({ kind, size = 16 }) => {
  const c = { width: size, height: size, viewBox: '0 0 18 18', fill: 'none', strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const }
  if (kind === 'model') {
    return <svg {...c}><rect x="2.5" y="3" width="13" height="9.5" rx="2" stroke="currentColor" strokeWidth="1.5" /><path d="M6 15h6M9 12.5V15" stroke="currentColor" strokeWidth="1.4" /></svg>
  }
  if (kind === 'agent') {
    return <svg {...c}><circle cx="4.5" cy="4.5" r="2" stroke="currentColor" strokeWidth="1.5" /><circle cx="13.5" cy="9" r="2" stroke="currentColor" strokeWidth="1.5" /><circle cx="4.5" cy="13.5" r="2" stroke="currentColor" strokeWidth="1.5" /><path d="M6.5 5.2L11.5 8M6.5 12.8L11.5 10" stroke="currentColor" strokeWidth="1.4" /></svg>
  }
  if (kind === 'tier') {
    return <svg {...c}><path d="M3 14h12M9 3v11M5 7l4-4 4 4" stroke="currentColor" strokeWidth="1.5" /></svg>
  }
  return <svg {...c}><circle cx="5" cy="4" r="1.8" stroke="currentColor" strokeWidth="1.4" /><circle cx="5" cy="14" r="1.8" stroke="currentColor" strokeWidth="1.4" /><circle cx="13.5" cy="9" r="1.8" stroke="currentColor" strokeWidth="1.4" /><path d="M5 5.8V12.2M5 7.2c0 1.8 3.2 1.8 6.7 1.8" stroke="currentColor" strokeWidth="1.4" /></svg>
}

interface SystemFlowDiagramProps {
  state: StateResponse | null
  router: RouterResponse | null
  providers: ProviderItem[]
  workspace?: WorkspaceStatus | null
  onNavigate?: (view: View) => void
  compact?: boolean
}

const clipText = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

export const SystemFlowDiagram: React.FC<SystemFlowDiagramProps> = ({ state, router, providers, workspace, onNavigate, compact = false }) => {
  const gridId = `caos-grid-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`   // one pattern per mounted diagram: two of them must not share an id
  const { needs, toReview, withPerson, runnable, closed, moving } = boardCounts(state)
  const agents = state?.agents ?? []
  const ollama = providers.find((p) => p.id === 'ollama')
  const ollamaOn = ollama?.status === 'online'
  const modelsCount = ollama?.models.length ?? 0
  const cloudReady = providers.filter((p) => p.type !== 'local' && (p.status === 'key_present' || p.status === 'ready' || p.status === 'online')).length
  const profilesCount = router?.profiles?.length ?? 0
  const tiersCount = router?.tiers?.length ?? 4
  const running = !!state?.running
  const waitsForRun = !running && runnable > 0          // nothing starts by itself: this stage is held until the operator presses Run
  const wtCount = workspace?.worktrees?.length ?? 0
  const branchText = workspace?.git_repo === false ? 'no git' : (workspace?.branch ?? 'main')
  const dirtyCount = workspace?.dirty_files?.length ?? 0

  if (compact) {
    return (
      <div className="sys-strip card" role="region" aria-label="Live harness pipeline">
        <div className="sys-strip-nodes">
          <button type="button" className="sys-node" onClick={() => onNavigate?.('console')}>
            <span className={`pip ${workspace?.git_repo ? 'on' : ''}`} aria-hidden="true" />
            <span><b>{state?.project || 'workspace'}</b><small>{branchText}{wtCount ? ` · ${wtCount} wt` : ''}</small></span>
          </button>
          <button type="button" className="sys-node" onClick={() => onNavigate?.('metrics')}>
            <span className={`pip ${profilesCount > 0 ? 'on' : ''}`} aria-hidden="true" />
            <span><b>Router</b><small>{profilesCount} measured · {tiersCount} tiers</small></span>
          </button>
          <button type="button" className="sys-node" onClick={() => onNavigate?.('providers')}>
            <span className={`pip ${ollamaOn ? 'on' : ''}`} aria-hidden="true" />
            <span><b>Engines</b><small>Ollama {ollamaOn ? `${modelsCount}m` : 'off'} · {agents.length} ag</small></span>
          </button>
          <button type="button" className={`sys-node ${needs > 0 ? 'due' : ''}`} onClick={() => onNavigate?.('board')} title={needs > 0 ? `${needs} waiting for your verdict` : undefined}>
            <span className={`pip ${needs > 0 ? 'warm' : closed > 0 ? 'on' : ''}`} aria-hidden="true" />
            <span><b>Verdict</b><small>{needs > 0 ? `${needs} waiting for you` : `${closed} closed`}</small></span>
          </button>
        </div>
      </div>
    )
  }

  // Five stages, each with the same four lines (number and name, headline, two facts). `human` marks the stages that stop for a person.
  const nodes = [
    { n: '01', name: 'WORKSPACE', title: state?.project || 'project', l1: `git: ${branchText}`, l2: `${dirtyCount} dirty · ${wtCount} wt`, target: 'console' as View, human: false, on: true },
    { n: '02', name: 'POLICY ROUTER', title: 'Evidence gate', l1: `${profilesCount} measured profile${profilesCount === 1 ? '' : 's'}`, l2: `${tiersCount} error-cost tiers`, target: 'metrics' as View, human: false, on: profilesCount > 0 },
    { n: '03', name: 'ENGINES', title: ollamaOn ? `Ollama · ${modelsCount}` : 'Ollama offline', l1: `${agents.length} configured agent${agents.length === 1 ? '' : 's'}`, l2: `${cloudReady} API key${cloudReady === 1 ? '' : 's'} present`, target: 'providers' as View, human: false, on: ollamaOn || agents.length > 0 },
    { n: '04', name: 'DISPATCH', title: running ? 'Running live' : waitsForRun ? `${runnable} ready` : 'Idle', l1: waitsForRun ? 'waits for you: Run' : `${moving} in motion`, l2: waitsForRun ? 'nothing starts alone' : 'shell off by default', target: 'board' as View, human: waitsForRun, on: running || waitsForRun },
    { n: '05', name: 'VERDICT', title: needs > 0 ? `${needs} wait you` : 'All clear', l1: needs > 0 ? `${toReview} review · ${withPerson} person` : `${closed} closed tasks`, l2: needs > 0 ? `${closed} closed` : 'reason required', target: 'board' as View, human: needs > 0, on: needs > 0 || closed > 0 },
  ].map((nd, i) => ({ ...nd, x: 8 + i * 200, y: 30, w: 184, h: 124 }))

  const wires = nodes.slice(0, -1).map((nd, i) => {
    const next = nodes[i + 1]
    const warm = next.human
    const active = i === 0 ? true : i === 1 ? profilesCount > 0 : i === 2 ? running || waitsForRun : needs > 0 || running
    return { x1: nd.x + nd.w, x2: next.x, active, warm }
  })

  const nodeLabel = (nd: (typeof nodes)[number]) => `Stage ${nd.n} ${nd.name.toLowerCase()}: ${nd.title}. ${nd.l1}. ${nd.l2}.${nd.human ? ' Waiting for you.' : ''} Opens ${nd.target === 'console' ? 'the console' : nd.target === 'metrics' ? 'the metrics view' : nd.target === 'providers' ? 'the providers' : 'the board'}.`

  return (
    <div className="card topology-card" role="region" aria-label="Live system topology">
      <div className="topology-head">
        <div>
          <h3>Live control plane signal path</h3>
          <p className="mute" style={{ margin: '2px 0 0', fontSize: 13.5 }}>Every box reads live runtime telemetry. Amber marks only the stages that are stopped for a person.</p>
        </div>
        <div className="topology-legend">
          <span><i className="pip on" aria-hidden="true" />automatic or idle</span>
          <span><i className="pip warm" aria-hidden="true" />waits for a person: 04 until you press Run, 05 until you give a verdict</span>
        </div>
      </div>
      <div className="topology-wrap">
        <svg viewBox="0 0 1000 184" className="topology-svg" role="group" aria-label={`Pipeline of five stages. Workspace ${state?.project || ''}, ${profilesCount} measured profiles, Ollama ${ollamaOn ? 'online' : 'offline'}, ${moving} in motion, ${needs} waiting for a person.`}>
          <defs>
            <pattern id={gridId} width="24" height="24" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="0.8" fill="rgba(245,242,236,0.10)" />
            </pattern>
          </defs>
          <rect x="1" y="1" width="998" height="182" rx="12" fill={`url(#${gridId})`} stroke="rgba(245,242,236,0.06)" />
          {wires.map((w, idx) => (
            <g key={idx} aria-hidden="true">
              <line x1={w.x1} y1="92" x2={w.x2} y2="92" stroke={w.warm ? 'var(--warm)' : w.active ? 'var(--ink-2)' : 'rgba(245,242,236,0.22)'} strokeWidth={w.active ? 1.8 : 1.2} strokeDasharray={w.active ? 'none' : '3 4'} />
              <polygon points={`${w.x2 - 5},88 ${w.x2},92 ${w.x2 - 5},96`} fill={w.warm ? 'var(--warm)' : w.active ? 'var(--ink-2)' : 'rgba(245,242,236,0.28)'} />
            </g>
          ))}
          {nodes.map((nd) => (
            <g key={nd.n} className={`topo-node ${nd.human ? 'warm' : ''}`} onClick={() => onNavigate?.(nd.target)} role="button" tabIndex={0} aria-label={nodeLabel(nd)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onNavigate?.(nd.target) } }}>
              <title>{`${nd.n} ${nd.name} · ${nd.title} · ${nd.l1} · ${nd.l2}`}</title>
              <rect x={nd.x} y={nd.y} width={nd.w} height={nd.h} rx="11" fill="var(--card-2)" stroke={nd.human ? 'var(--warm)' : nd.on ? 'rgba(245,242,236,0.3)' : 'rgba(245,242,236,0.12)'} strokeWidth={nd.human ? 1.6 : 1.1} />
              <text x={nd.x + 14} y={nd.y + 27} className={`topo-num ${nd.human ? 'warm' : ''}`}>{nd.n}</text>
              <text x={nd.x + 44} y={nd.y + 27} className={`topo-tag ${nd.human ? 'warm' : ''}`}>{nd.name}</text>
              <circle cx={nd.x + nd.w - 16} cy={nd.y + 21} r="4" fill={nd.human ? 'var(--warm)' : nd.on ? 'var(--ink)' : 'var(--ink-3)'} />
              <text x={nd.x + 14} y={nd.y + 62} className="topo-title">{clipText(nd.title, 15)}</text>
              <text x={nd.x + 14} y={nd.y + 88} className="topo-l1">{clipText(nd.l1, 20)}</text>
              <text x={nd.x + 14} y={nd.y + 110} className="topo-l2">{clipText(nd.l2, 20)}</text>
            </g>
          ))}
        </svg>
      </div>
    </div>
  )
}

/* ── The core: where a session starts ──────────────────────────────────────────────────────────────────────────────
   One emblem for the four stages (Plan, Act, Verify, Review) and the router that feeds them. Nothing here is decoration:
   a node's colour is the state of what it stands for (questions waiting, a run in progress, the repository gates, tasks
   waiting for you), the halo follows the mode, and the only motion is the amber tick, which moves only while a run works. */

export type CoreStage = 'plan' | 'act' | 'verify' | 'review'
export type CoreTone = 'idle' | 'active' | 'ok' | 'wait' | 'fail'
export interface CoreNode { id: CoreStage; label: string; detail: string; tone: CoreTone; /** The long reading, for assistive tech and the tooltip; `detail` is what fits beside the node. */ full?: string }
export interface CoreMetrics { success: number | null; redo: number | null; p50: number | null; runs: number }
export interface CoreData {
  nodes: CoreNode[]
  running: boolean
  mode: 'plan' | 'act'
  engine: string
  engineOnline: boolean
  routerNote: string
  profile: string
  metrics: CoreMetrics | null
}

const TONE_COLOR: Record<CoreTone, string> = { idle: 'var(--ink-3)', active: 'var(--plan)', ok: 'var(--pass)', wait: 'var(--act)', fail: 'var(--fail)' }
const toneOf = (n: CoreNode, mode: 'plan' | 'act') => (n.tone === 'active' ? (n.id === 'act' || mode === 'act' ? 'var(--act)' : 'var(--plan)') : TONE_COLOR[n.tone])
const rad = (deg: number) => (deg * Math.PI) / 180
const pt = (cx: number, cy: number, r: number, bearing: number) => [cx + r * Math.sin(rad(bearing)), cy - r * Math.cos(rad(bearing))] as const
const arc = (cx: number, cy: number, r: number, a0: number, a1: number) => {
  const [x0, y0] = pt(cx, cy, r, a0)
  const [x1, y1] = pt(cx, cy, r, a1)
  return `M${x0.toFixed(1)} ${y0.toFixed(1)} A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`
}
const short = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s)
const LETTER: Record<CoreStage, string> = { plan: 'P', act: 'A', verify: 'V', review: 'R' }
const keyAct = (fn: () => void) => (e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } }

interface CoreProps {
  data: CoreData
  onNode: (id: CoreStage) => void
  onRouter: () => void
}

export const CaosCore: React.FC<CoreProps> = ({ data, onNode, onRouter }) => {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const C = 160, Y = 140, R = 92
  const bearings: Record<CoreStage, number> = { plan: 315, act: 45, verify: 135, review: 225 }
  const order: CoreStage[] = ['plan', 'act', 'verify', 'review']
  const halo = data.mode === 'act' ? 'var(--act)' : 'var(--plan)'
  return (
    <div className={`core ${data.running ? 'is-running' : ''}`}>
      <svg className="core-svg" viewBox="-50 0 420 288" role="group" aria-label="Núcleo CAOS: Plan, Act, Verify, Review">
        <defs>
          <radialGradient id={`core-${uid}`} cx="50%" cy="46%" r="60%"><stop offset="0" stopColor="rgb(var(--hl))" stopOpacity=".16" /><stop offset=".55" stopColor="rgb(var(--hl))" stopOpacity=".04" /><stop offset="1" stopColor="rgb(var(--hl))" stopOpacity="0" /></radialGradient>
          <radialGradient id={`halo-${uid}`} cx="50%" cy="50%" r="50%"><stop offset=".78" stopColor={halo} stopOpacity="0" /><stop offset=".93" stopColor={halo} stopOpacity=".18" /><stop offset="1" stopColor={halo} stopOpacity="0" /></radialGradient>
          <filter id={`float-${uid}`} x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="3" stdDeviation="3" floodColor="#000" floodOpacity=".5" /></filter>
        </defs>
        <circle cx={C} cy={Y} r={128} fill={`url(#halo-${uid})`} className="core-halo" />
        <circle cx={C} cy={Y} r={R + 14} className="core-ring outer" />
        {Array.from({ length: 60 }, (_, i) => {
          const b = i * 6
          const major = i % 5 === 0
          const [x0, y0] = pt(C, Y, major ? R + 6 : R + 9, b)
          const [x1, y1] = pt(C, Y, R + 14, b)
          return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} className={major ? 'core-scale major' : 'core-scale'} />
        })}
        <circle cx={C} cy={Y} r={R} className="core-ring" />
        <circle cx={C} cy={Y} r={64} className="core-ring inner" />
        <circle cx={C} cy={Y} r={64} fill={`url(#core-${uid})`} />
        {order.map((id, i) => {
          const next = order[(i + 1) % 4]
          const node = data.nodes.find((n) => n.id === id)!
          return <path key={id} d={arc(C, Y, R, bearings[id] + 15, bearings[next] - 15)} className="core-seg" style={{ stroke: toneOf(node, data.mode) }} />
        })}
        {/* The amber tick at twelve o'clock: still when idle, a dot that circles the ring while a run works. */}
        <line x1={C} y1={Y - R - 20} x2={C} y2={Y - R - 34} className="core-tick" />
        {data.running && <g className="core-sweep" style={{ transformOrigin: `${C}px ${Y}px` }}><circle cx={C} cy={Y - R} r={4.5} className="core-dot" /></g>}
        {order.map((id) => {
          const node = data.nodes.find((n) => n.id === id)!
          const [x, y] = pt(C, Y, R, bearings[id])
          const [lx, ly] = pt(C, Y, R + 32, bearings[id])
          const col = toneOf(node, data.mode)
          const right = lx > C
          return (
            <g key={id} className="core-node" role="button" tabIndex={0} aria-label={`${node.label}: ${node.full ?? node.detail}`} onClick={() => onNode(id)} onKeyDown={keyAct(() => onNode(id))}>
              <title>{node.full ?? node.detail}</title>
              <circle cx={x} cy={y} r={17} className="core-node-bg" style={{ stroke: col }} filter={`url(#float-${uid})`} />
              <text x={x} y={y + 4} textAnchor="middle" className="core-letter" style={{ fill: col }}>{LETTER[id]}</text>
              <text x={lx + (right ? 8 : -8)} y={ly - 1} textAnchor={right ? 'start' : 'end'} className="core-label">{node.label}</text>
              <text x={lx + (right ? 8 : -8)} y={ly + 13} textAnchor={right ? 'start' : 'end'} className="core-sub">{short(node.detail, 16)}</text>
            </g>
          )
        })}
        <g className="core-center" role="button" tabIndex={0} aria-label={`Router: ${data.routerNote}`} onClick={onRouter} onKeyDown={keyAct(onRouter)}>
          <circle cx={C} cy={Y} r={42} className="core-center-bg" />
          <text x={C} y={Y - 12} textAnchor="middle" className="core-sub">ROUTER · {data.profile}</text>
          <text x={C} y={Y + 5} textAnchor="middle" className="core-engine">{short(data.engine, 17)}</text>
          <circle cx={C} cy={Y + 20} r={3.5} style={{ fill: data.engineOnline ? 'var(--pass)' : 'var(--fail)' }} />
        </g>
      </svg>
    </div>
  )
}

/** The mark: a ring inside a ring, rays between, and the single amber tick at twelve o'clock (the same one the terminal draws). */
export const CaosMark: React.FC<{ size?: number }> = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" className="caos-mark">
    <circle cx="12" cy="12" r="8.4" stroke="rgb(var(--hl))" strokeWidth="1.4" />
    <circle cx="12" cy="12" r="4.6" stroke="rgb(var(--hl))" strokeOpacity=".55" strokeWidth="1.2" />
    <path d="M12 12L18 6M12 12L6 18" stroke="rgb(var(--hl))" strokeOpacity=".4" strokeWidth="1" strokeLinecap="round" />
    <path d="M12 0.8V3.4" stroke="var(--warm)" strokeWidth="2" strokeLinecap="round" />
  </svg>
)


/* The work cycle as four plain cards: what each stage says right now, and a click that goes there. Replaces the ring: same data, readable. */
const STAGE_ICON: Record<string, React.FC<{ size?: number; className?: string }>> = { plan: Eye, act: PencilSimple, verify: ShieldCheck, review: ListChecks }

export const StageRow: React.FC<{ data: CoreData; onNode: (id: CoreStage) => void; onRouter: () => void }> = ({ data, onNode, onRouter }) => (
  <section className="stage-row" aria-label="Work cycle">
    <ol className="stage-list">
      {data.nodes.map((n, i) => {
        const Icon = STAGE_ICON[n.id] ?? Eye
        const current = (n.id === 'plan' && data.mode === 'plan') || (n.id === 'act' && data.mode === 'act')
        return (
          <li key={n.id}>
            <button type="button" className={`stage tone-${n.tone} ${current ? 'is-current' : ''}`} onClick={() => onNode(n.id as CoreStage)}>
              <span className="stage-top"><Icon size={20} className="stage-ico" /><span className="stage-n">{i + 1}</span></span>
              <b>{n.label}</b>
              <small>{n.detail}</small>
            </button>
          </li>
        )
      })}
    </ol>
    <button type="button" className="stage-engine" onClick={onRouter} title="Change the engine">
      <Cpu size={16} />
      <span className={`pip ${data.engineOnline ? 'on' : ''}`} aria-hidden="true" />
      <b>{data.engine}</b>
      <small>{data.routerNote}</small>
    </button>
  </section>
)
