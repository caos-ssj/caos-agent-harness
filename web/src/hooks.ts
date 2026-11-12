import { useCallback, useEffect, useRef, useState } from 'react'

const reducedMotion = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Keeps something mounted for `ms` after it is closed, so it can play its exit. `leaving` is true during that time: the caller sets
 *  a `data-leaving` attribute (the CSS animates it and drops pointer events) and renders nothing once `mounted` is false. */
export function usePresence(open: boolean, ms = 160) {
  const [mounted, setMounted] = useState(open)
  useEffect(() => {
    if (open) { setMounted(true); return }
    if (!mounted) return
    const t = window.setTimeout(() => setMounted(false), reducedMotion() ? 0 : ms)
    return () => window.clearTimeout(t)
  }, [open, ms, mounted])
  return { mounted: open || mounted, leaving: !open && mounted }
}

/** Rows that appear after the first paint get `fresh` and so play their entrance once. Rows that were already there, or that mount again
 *  when a tab is switched or a poll lands, do not play it again. */
export function useFresh(ids: Array<string | number>): Set<string | number> {
  const seen = useRef<Set<string | number> | null>(null)
  const fresh = new Set<string | number>()
  if (seen.current) for (const id of ids) if (!seen.current.has(id)) fresh.add(id)
  useEffect(() => { seen.current = new Set(ids) })
  return fresh
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** What a dialog owes the keyboard: focus goes in when it opens and returns to where it was when it closes, Escape closes it, and a
 *  modal one keeps Tab inside. `initial` picks the element to focus first (default: the first focusable one). */
export function useDialog<T extends HTMLElement>(open: boolean, onClose: () => void, opts: { modal?: boolean; initial?: string; focus?: boolean; escapeAnywhere?: boolean } = {}) {
  const ref = useRef<T>(null)
  const back = useRef<HTMLElement | null>(null)
  const close = useRef(onClose)
  close.current = onClose
  const { modal, initial, focus = true, escapeAnywhere = false } = opts
  useEffect(() => {
    if (!open) return
    back.current = document.activeElement as HTMLElement | null
    const node = ref.current
    const target = (initial && node?.querySelector<HTMLElement>(initial)) || node?.querySelector<HTMLElement>(FOCUSABLE) || node
    if (focus && target) { if (!target.hasAttribute('tabindex') && target === node) target.setAttribute('tabindex', '-1'); target.focus({ preventScroll: true }) }
    const key = (e: KeyboardEvent) => {
      if (!node) return
      const inside = node.contains(document.activeElement)
      // A docked panel (escapeAnywhere) also closes on Escape from elsewhere in the page, but never while a popover, palette or question is open: those take it first.
      const free = escapeAnywhere && !document.querySelector('.scrim, .pop, .attach-pop, .confirm, .run-card')
      if (e.key === 'Escape' && (inside || modal || free)) { e.preventDefault(); e.stopPropagation(); close.current() }
      else if (e.key === 'Tab' && modal) {
        const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null)
        if (!items.length) { e.preventDefault(); return }
        const first = items[0], last = items[items.length - 1]
        if (e.shiftKey && (document.activeElement === first || !inside)) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && (document.activeElement === last || !inside)) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('keydown', key, true)
      const b = back.current
      const here = document.activeElement
      // Focus goes back only if it was in the dialog (or lost with it): never pull it away from where the user has moved on to.
      if (b && document.contains(b) && (!here || here === document.body || node?.contains(here))) b.focus({ preventScroll: true })
    }
  }, [open, modal, initial, focus, escapeAnywhere])
  return ref
}

/** `true` while a media query holds. */
export function useMedia(query: string) {
  const get = useCallback(() => typeof window !== 'undefined' && !!window.matchMedia?.(query).matches, [query])
  const [on, setOn] = useState(get)
  useEffect(() => {
    const m = window.matchMedia(query)
    const h = () => setOn(m.matches)
    h()
    m.addEventListener('change', h)
    return () => m.removeEventListener('change', h)
  }, [query])
  return on
}
