import React, { useCallback, useEffect, useRef, useState } from 'react'
import { FileCode2, Quote, X } from '../icons'

/* Notes written against a delivery while reviewing it. Each one quotes what it is about (a piece of the result the reviewer selected,
   or a line of the diff) and says what to fix. They pile up under the result and leave together, as one return: a line per note. */

export interface ReviewNote {
  id: number
  quote: string
  note: string
  from: 'text' | 'diff'
}

export const QUOTE_MAX = 200
/** Mirrors MAX_NOTE and MAX_NOTE_LINES in caos_harness/web/server.py: the server refuses anything longer, it never cuts it. */
export const NOTE_MAX = 4000
export const NOTE_LINES_MAX = 40

const oneLine = (s: string) => s.replace(/\s+/g, ' ').trim()

export function cleanQuote(raw: string): string {
  const q = oneLine(raw)
  return q.length > QUOTE_MAX ? q.slice(0, QUOTE_MAX - 1).trimEnd() + '…' : q
}

/** The one reason a verdict carries: the general note first, then each inline note on its own line as `“quote” → what to fix`. */
export function composeReason(general: string, notes: ReviewNote[]): string {
  return [oneLine(general), ...notes.map((n) => (oneLine(n.note) ? `“${n.quote}” → ${oneLine(n.note)}` : `“${n.quote}”`))].filter(Boolean).join('\n')
}

export interface PickedQuote {
  text: string
  top: number
  left: number
}

/** The text selected inside `ref` (and only inside it), with where its last line ends, relative to `ref`'s offset parent. */
export function useSelectionQuote(ref: React.RefObject<HTMLElement | null>, enabled: boolean): [PickedQuote | null, () => void] {
  const [picked, setPicked] = useState<PickedQuote | null>(null)
  const clear = useCallback(() => setPicked(null), [])
  useEffect(() => {
    if (!enabled) { setPicked(null); return }
    const read = () => {
      const node = ref.current
      const sel = window.getSelection()
      if (!node || !sel || sel.rangeCount === 0 || sel.isCollapsed || !node.contains(sel.anchorNode) || !node.contains(sel.focusNode)) { setPicked(null); return }
      const text = cleanQuote(sel.toString())
      if (!text) { setPicked(null); return }
      const range = sel.getRangeAt(0)
      const rects = typeof range.getClientRects === 'function' ? Array.from(range.getClientRects()) : []
      const last = rects[rects.length - 1] ?? node.getBoundingClientRect()
      const host = (node.offsetParent as HTMLElement | null) ?? node
      const box = host.getBoundingClientRect()
      const left = Math.min(Math.max(last.right - box.left + 6, 4), Math.max(4, box.width - 40))
      setPicked({ text, top: last.top - box.top + host.scrollTop - 4, left })
    }
    document.addEventListener('selectionchange', read)
    return () => document.removeEventListener('selectionchange', read)
  }, [ref, enabled])
  return [picked, clear]
}

interface ReviewNoteListProps {
  notes: ReviewNote[]
  /** The note to put the cursor in: the one that was just added. */
  focusId: number | null
  onChange: (id: number, note: string) => void
  onRemove: (id: number) => void
  onDone: () => void
}

export const ReviewNoteList: React.FC<ReviewNoteListProps> = ({ notes, focusId, onChange, onRemove, onDone }) => {
  const list = useRef<HTMLOListElement>(null)
  useEffect(() => {
    if (focusId == null) return
    list.current?.querySelector<HTMLInputElement>(`[data-note="${focusId}"]`)?.focus({ preventScroll: false })
  }, [focusId])
  if (notes.length === 0) return null
  return (
    <ol className="rnotes" ref={list} aria-label="Notas de esta revisión">
      {notes.map((n, i) => (
        <li key={n.id} className="rnote">
          <span className="rnote-n mono" aria-hidden="true">{i + 1}</span>
          <div className="rnote-body">
            <q className="rnote-quote" title={n.quote}>
              {n.from === 'diff' ? <FileCode2 className="icon" aria-hidden="true" /> : <Quote className="icon" aria-hidden="true" />}
              <span>{n.quote}</span>
            </q>
            <input
              className="field field-sm"
              data-note={n.id}
              value={n.note}
              maxLength={600}
              onChange={(e) => onChange(n.id, e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); onDone() } }}
              placeholder="Qué corregir aquí…"
              aria-label={`Nota ${i + 1}: qué corregir`}
            />
          </div>
          <button type="button" className="btn btn-quiet btn-icon btn-xs" onClick={() => onRemove(n.id)} aria-label={`Quitar la nota ${i + 1}`}>
            <X className="icon" aria-hidden="true" />
          </button>
        </li>
      ))}
    </ol>
  )
}
