import React, { useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronUp, Columns2, Copy, Lock, MessageSquarePlus, Plus, Rows2, Send, X } from '../icons'

interface DiffLine {
  type: 'hunk' | 'add' | 'del' | 'context' | 'note'
  oldNo: number | null
  newNo: number | null
  text: string
  raw: string
}

interface DiffFileBlock {
  file: string
  additions: number
  deletions: number
  lines: DiffLine[]
  /** Set when the block carries no hunks on purpose: the file is binary, or the harness withheld it as secret-like. */
  redacted?: boolean
}

/** Longer blocks fold to this many lines until "Show all" is pressed. */
export const FOLD_AFTER = 80
export const FOLD_SHOWS = 40

export function extractDiffBlocks(rawText: string | null | undefined): string {
  if (!rawText) return ''
  const text = rawText.trim()
  if (/^(diff --git |---\s+\S+|\+\+\+\s+\S+|@@\s+-\d+)/m.test(text)) {
    return text
  }
  const fenced = Array.from(text.matchAll(/```(?:diff|patch)\s*\n([\s\S]*?)```/gi)).map((m) => m[1].trim()).filter(Boolean)
  return fenced.join('\n')
}

export function parseUnifiedDiff(diffText: string): DiffFileBlock[] {
  const blocks: DiffFileBlock[] = []
  let current: DiffFileBlock | null = null
  let oldLine = 0
  let newLine = 0

  const ensureCurrent = (name = 'delivery.patch') => {
    if (!current) {
      current = { file: name, additions: 0, deletions: 0, lines: [] }
      blocks.push(current)
    }
    return current
  }

  for (const raw of diffText.split(/\r?\n/)) {
    if (raw.startsWith('diff --git ')) {
      const match = raw.match(/^diff --git a\/(.+?) b\/(.+)$/)
      current = { file: match ? match[2] : raw.slice(11), additions: 0, deletions: 0, lines: [] }
      blocks.push(current)
      continue
    }
    if (raw.startsWith('+++ ')) {
      const target = raw.slice(4).replace(/^b\//, '').trim()
      if (!current) {
        ensureCurrent(target === '/dev/null' ? 'deleted-file' : target)
      } else if (target && target !== '/dev/null') {
        current.file = target
      }
      continue
    }
    if (raw.startsWith('--- ') || raw.startsWith('index ') || raw.startsWith('new file mode ') || raw.startsWith('deleted file mode ') ||
        /^(old mode|new mode|similarity index|dissimilarity index|rename from|rename to|copy from|copy to) /.test(raw)) {
      continue
    }
    // Lines `git diff` writes that are not file content: they are shown as notes, never numbered, counted or quoted.
    if (raw.startsWith('\\ ')) {                                   // "\ No newline at end of file"
      ensureCurrent().lines.push({ type: 'note', oldNo: null, newNo: null, text: raw.slice(2), raw })
      continue
    }
    const redacted = /^\(redacted: /.test(raw) ? raw.match(/^\(redacted: (.*)\)$/) : raw.match(/^new file \((.*)\)$/)   // the server's withheld files, and its synthetic new-file blocks
    if (redacted) {
      const b = ensureCurrent()
      b.redacted = true
      b.lines.push({ type: 'note', oldNo: null, newNo: null, text: /secret/.test(redacted[1]) ? `Withheld: ${redacted[1].replace(/^redacted: /, '')}` : redacted[1].charAt(0).toUpperCase() + redacted[1].slice(1), raw })
      continue
    }
    if (/^Binary files .* differ$/.test(raw) || raw === 'GIT binary patch') {
      const b = ensureCurrent()
      b.redacted = true
      b.lines.push({ type: 'note', oldNo: null, newNo: null, text: raw === 'GIT binary patch' ? 'Binary file changed' : 'Binary file changed (no text diff)', raw })
      continue
    }
    if (/^\.\.\. \[diff truncated/.test(raw)) {                      // the server cut the diff at 64 KB
      ensureCurrent().lines.push({ type: 'note', oldNo: null, newNo: null, text: raw.replace(/^\.\.\. \[|\]$/g, ''), raw })
      continue
    }
    const hunk = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/)
    if (hunk) {
      oldLine = Number(hunk[1])
      newLine = Number(hunk[2])
      ensureCurrent().lines.push({ type: 'hunk', oldNo: null, newNo: null, text: raw, raw })
      continue
    }
    if (!current) continue                                          // prose before the first file or hunk ("Patch ready.") is not part of any file
    const block = ensureCurrent()
    if (raw.startsWith('+')) {
      block.additions += 1
      block.lines.push({ type: 'add', oldNo: null, newNo: newLine++, text: raw.slice(1), raw })
    } else if (raw.startsWith('-')) {
      block.deletions += 1
      block.lines.push({ type: 'del', oldNo: oldLine++, newNo: null, text: raw.slice(1), raw })
    } else {
      const clean = raw.startsWith(' ') ? raw.slice(1) : raw
      block.lines.push({ type: 'context', oldNo: oldLine++, newNo: newLine++, text: clean, raw })
    }
  }
  return blocks
}

interface DiffViewerProps {
  diffText: string
  onAnnotateLine?: (snippet: string) => void
  annotateLabel?: string
  emptyMessage?: string
  /** When given, a line's `+` writes a draft note into a tray, and the whole tray is sent together here. */
  onSendDrafts?: (text: string) => void
}

interface Draft { id: number; cite: string; note: string }
type Mode = 'unified' | 'split'
const MODE_KEY = 'caos_diff_mode'

const readMode = (): Mode => {
  try { return localStorage.getItem(MODE_KEY) === 'split' ? 'split' : 'unified' } catch { return 'unified' }
}

/** Pairs a block's lines for the side-by-side view: a run of removals sits beside the run of additions that replaced it. */
export function splitRows(lines: DiffLine[]): Array<{ left?: DiffLine; right?: DiffLine; full?: DiffLine }> {
  const rows: Array<{ left?: DiffLine; right?: DiffLine; full?: DiffLine }> = []
  let i = 0
  while (i < lines.length) {
    const ln = lines[i]
    if (ln.type === 'hunk' || ln.type === 'note') { rows.push({ full: ln }); i++; continue }
    if (ln.type === 'context') { rows.push({ left: ln, right: ln }); i++; continue }
    const dels: DiffLine[] = []
    const adds: DiffLine[] = []
    while (i < lines.length && lines[i].type === 'del') dels.push(lines[i++])
    while (i < lines.length && lines[i].type === 'add') adds.push(lines[i++])
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) rows.push({ left: dels[k], right: adds[k] })
  }
  return rows
}

export const DiffViewer: React.FC<DiffViewerProps> = ({
  diffText,
  onAnnotateLine,
  annotateLabel = 'Add to review note',
  emptyMessage = 'No unified diff hunks present.',
  onSendDrafts,
}) => {
  const [copiedFile, setCopiedFile] = useState<string | null>(null)
  const [unfolded, setUnfolded] = useState<Record<string, boolean>>({})
  const [mode, setModeState] = useState<Mode>(readMode)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [composing, setComposing] = useState<{ cite: string; text: string } | null>(null)
  const nextId = useRef(1)
  const blocks = useMemo(() => parseUnifiedDiff(diffText), [diffText])

  if (!diffText.trim() || blocks.length === 0) {
    return <p className="muted">{emptyMessage}</p>
  }

  const setMode = (m: Mode) => {
    setModeState(m)
    try { localStorage.setItem(MODE_KEY, m) } catch { /* ignore */ }
  }
  const copyRaw = (file: string, lines: DiffLine[]) => {
    const out = lines.map((l) => l.raw).join('\n')
    navigator.clipboard.writeText(out)
    setCopiedFile(file)
    window.setTimeout(() => setCopiedFile((c) => (c === file ? null : c)), 1400)
  }
  const annotate = (cite: string) => {
    if (onSendDrafts) setComposing({ cite, text: '' })
    else onAnnotateLine?.(cite)
  }
  const saveDraft = () => {
    if (!composing) return
    setDrafts((d) => [...d, { id: nextId.current++, cite: composing.cite, note: composing.text.trim() }])
    setComposing(null)
  }
  const sendDrafts = () => {
    if (!drafts.length) return
    onSendDrafts?.(`Comentarios de revisión (${drafts.length}):\n` + drafts.map((d) => `- ${d.cite}${d.note ? ` → ${d.note}` : ''}`).join('\n'))
    setDrafts([])
  }
  const canAnnotate = !!(onAnnotateLine || onSendDrafts)

  const plusBtn = (cite: string, file: string, lineNum: number | string) => canAnnotate && (
    <button type="button" className="diff-plus" title={onSendDrafts ? 'Comentar esta línea' : annotateLabel} aria-label={`${annotateLabel}: ${file} line ${lineNum}`} onClick={() => annotate(cite)}>
      {onSendDrafts ? <MessageSquarePlus className="icon icon-sm" aria-hidden="true" /> : <Plus className="icon icon-sm" aria-hidden="true" />}
    </button>
  )
  const citeOf = (file: string, ln: DiffLine) => {
    const lineNum = ln.newNo ?? ln.oldNo ?? ''
    return `[${file}${lineNum ? `:${lineNum}` : ''}] ${ln.type === 'add' ? '+' : ln.type === 'del' ? '-' : ''}${ln.text.trim().slice(0, 120)}`
  }

  return (
    <div className="diff-viewer" role="region" aria-label="Unified code diff">
      <div className="diff-toolbar">
        <div className="seg" role="group" aria-label="Vista del diff">
          <button type="button" aria-pressed={mode === 'unified'} onClick={() => setMode('unified')} title="Una columna"><Rows2 className="icon icon-sm" aria-hidden="true" />Unificado</button>
          <button type="button" aria-pressed={mode === 'split'} onClick={() => setMode('split')} title="Antes y después, lado a lado"><Columns2 className="icon icon-sm" aria-hidden="true" />Split</button>
        </div>
        <span className="mono muted">{blocks.length} {blocks.length === 1 ? 'archivo' : 'archivos'}</span>
      </div>

      {blocks.map((blk, bi) => {
        const key = `${blk.file}-${bi}`
        const total = blk.lines.length
        const foldable = total > FOLD_AFTER
        const open = !foldable || !!unfolded[key]
        const shown = open ? blk.lines : blk.lines.slice(0, FOLD_SHOWS)
        const bodyId = `diff-body-${bi}`
        return (
          <section key={key} className={`diff-file ${blk.redacted ? 'withheld' : ''}`}>
            <header className="diff-file-head">
              <span className="diff-file-name mono" title={blk.file}>{blk.file}</span>
              <span className="diff-counts mono" title={`${blk.additions} added, ${blk.deletions} removed, ${total} lines in this block`}>
                {blk.redacted ? <b className="withheld-tag"><Lock className="icon icon-xs" aria-hidden="true" />no text</b> : (
                  <>
                    <b className="plus">+{blk.additions}</b>
                    <b className="minus">-{blk.deletions}</b>
                    <span className="diff-total">{total} {total === 1 ? 'line' : 'lines'}</span>
                  </>
                )}
              </span>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => copyRaw(blk.file, blk.lines)}>
                {copiedFile === blk.file ? <Check className="icon icon-sm" aria-hidden="true" /> : <Copy className="icon icon-sm" aria-hidden="true" />}
                {copiedFile === blk.file ? 'Copied' : 'Copy'}
              </button>
            </header>
            <div className={`diff-lines ${mode === 'split' ? 'is-split' : ''}`} id={bodyId}>
              {mode === 'split' ? splitRows(shown).map((row, ri) => {
                if (row.full) {
                  const ln = row.full
                  return ln.type === 'hunk'
                    ? <div key={ri} className="diff-line hunk"><span className="ln" /><span className="sig">@@</span><code className="code">{ln.text}</code></div>
                    : <div key={ri} className="diff-line note"><span className="note-text">{ln.text}</span></div>
                }
                const cell = (ln: DiffLine | undefined, side: 'l' | 'r') => ln ? (
                  <div className={`split-cell ${ln.type}`}>
                    <span className="ln tabular">{side === 'l' ? ln.oldNo ?? '' : ln.newNo ?? ''}</span>
                    <code className="code">{ln.text || ' '}</code>
                    {ln.type !== 'context' && plusBtn(citeOf(blk.file, ln), blk.file, ln.newNo ?? ln.oldNo ?? ri + 1)}
                  </div>
                ) : <div className="split-cell empty" />
                return <div key={ri} className="split-row">{cell(row.left, 'l')}{cell(row.right, 'r')}</div>
              }) : shown.map((ln, li) => {
                if (ln.type === 'hunk') {
                  return <div key={li} className="diff-line hunk"><span className="ln" /><span className="ln" /><span className="sig">@@</span><code className="code">{ln.text}</code></div>
                }
                if (ln.type === 'note') {
                  return <div key={li} className="diff-line note"><span className="note-text">{blk.redacted ? <Lock className="icon icon-xs" aria-hidden="true" /> : null}{ln.text}</span></div>
                }
                const lineNum = ln.newNo ?? ln.oldNo ?? ''
                return (
                  <div key={li} className={`diff-line ${ln.type}`}>
                    <span className="ln tabular">{ln.oldNo ?? ''}</span>
                    <span className="ln tabular">{ln.newNo ?? ''}</span>
                    <span className="sig">{ln.type === 'add' ? '+' : ln.type === 'del' ? '-' : ' '}</span>
                    <code className="code">{ln.text || ' '}</code>
                    {plusBtn(citeOf(blk.file, ln), blk.file, lineNum || li + 1)}
                  </div>
                )
              })}
            </div>
            {foldable && (
              <button type="button" className="diff-fold" aria-expanded={open} aria-controls={bodyId} onClick={() => setUnfolded((cur) => ({ ...cur, [key]: !open }))}>
                {open ? <ChevronUp className="icon icon-sm" aria-hidden="true" /> : <ChevronDown className="icon icon-sm" aria-hidden="true" />}
                {open ? `Show fewer lines` : `Show all ${total} lines (${total - FOLD_SHOWS} more)`}
              </button>
            )}
          </section>
        )
      })}

      {onSendDrafts && (composing || drafts.length > 0) && (
        <div className="draft-tray" role="region" aria-label="Comentarios de revisión">
          {composing && (
            <form className="draft-compose" onSubmit={(e) => { e.preventDefault(); saveDraft() }}>
              <code className="mono muted">{composing.cite}</code>
              <input className="field field-sm" autoFocus value={composing.text} placeholder="¿Qué debe cambiar aquí? (Enter guarda el borrador)" onChange={(e) => setComposing({ ...composing, text: e.target.value })} onKeyDown={(e) => { if (e.key === 'Escape') setComposing(null) }} />
              <button type="submit" className="btn btn-xs">Guardar</button>
              <button type="button" className="btn btn-quiet btn-xs btn-icon" aria-label="Cancelar" onClick={() => setComposing(null)}><X className="icon icon-xs" aria-hidden="true" /></button>
            </form>
          )}
          {drafts.length > 0 && (
            <>
              <div className="draft-head"><b>Comentarios de revisión ({drafts.length})</b><span className="muted">se envían juntos, no uno a uno</span></div>
              <ul className="draft-list">
                {drafts.map((d) => (
                  <li key={d.id}><code className="mono">{d.cite}</code><span>{d.note || <em className="muted">sin nota</em>}</span>
                    <button type="button" className="btn btn-quiet btn-xs btn-icon" aria-label="Quitar borrador" onClick={() => setDrafts((all) => all.filter((x) => x.id !== d.id))}><X className="icon icon-xs" aria-hidden="true" /></button>
                  </li>
                ))}
              </ul>
              <div className="draft-foot">
                <button type="button" className="btn btn-primary btn-sm" onClick={sendDrafts}><Send className="icon icon-sm" aria-hidden="true" />Enviar {drafts.length} al compositor</button>
                <button type="button" className="btn btn-quiet btn-sm" onClick={() => setDrafts([])}>Descartar</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
