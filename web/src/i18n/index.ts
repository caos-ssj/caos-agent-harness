import { EN, EN_INLINE, EN_PATTERNS } from './en'

export type Lang = 'en' | 'es'
const KEY = 'caos-lang'
const ATTRS = ['title', 'placeholder', 'aria-label', 'alt']

export function getLang(): Lang {
  try {
    return localStorage.getItem(KEY) === 'es' ? 'es' : 'en'   // English unless the person chose Spanish
  } catch {
    return 'en'
  }
}

export function setLang(lang: Lang): void {
  try {
    localStorage.setItem(KEY, lang)
  } catch { /* private mode: the choice lasts until the page closes */ }
  window.location.reload()
}

/** The English for one piece of text, or the text itself when there is none. Spacing around it is kept. */
export function translate(text: string): string {
  const core = text.trim()
  if (!core) return text
  const lead = text.slice(0, text.indexOf(core)), tail = text.slice(text.indexOf(core) + core.length)
  const hit = EN[core]
  if (hit !== undefined) return lead + hit + tail
  for (const [re, rep] of EN_PATTERNS) {
    if (re.test(core)) return lead + EN_INLINE.reduce((t, [es, en]) => t.split(es).join(en), translate(core.replace(re, rep as string))) + tail   // a second pass: what the pattern kept may be in the list
  }
  const parts = core.split(/( · |: )/)   // "Plan: solo lectura", "3 skill(s) de Código & Infra": each side on its own
  if (parts.length > 1) {
    const done = parts.map((p, i) => (i % 2 ? p : translate(p)))
    if (done.join('') !== core) return lead + done.join('') + tail
  }
  return text
}

function walk(root: Node): void {
  if (root.nodeType === Node.TEXT_NODE) {
    const t = root as Text
    const next = translate(t.data)
    if (next !== t.data) t.data = next
    return
  }
  if (root.nodeType !== Node.ELEMENT_NODE) return
  const el = root as Element
  if (['SCRIPT', 'STYLE'].includes(el.tagName)) return
  for (const a of ATTRS) {
    const v = el.getAttribute(a)
    if (v) {
      const next = translate(v)
      if (next !== v) el.setAttribute(a, next)
    }
  }
  if (['CODE', 'PRE', 'TEXTAREA'].includes(el.tagName)) return   // what is typed or quoted is never translated
  el.childNodes.forEach(walk)
}

/** Translates the page now and keeps translating what React draws later. Only in English: Spanish is the text as written. */
export function startTranslator(root: HTMLElement = document.body): void {
  if (getLang() !== 'en') return
  document.documentElement.lang = 'en'
  let queued = false
  const pending = new Set<Node>()
  const flush = () => {
    queued = false
    obs.disconnect()
    pending.forEach(walk)
    pending.clear()
    obs.observe(root, opts)
  }
  const opts: MutationObserverInit = { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS }
  const obs = new MutationObserver((muts) => {
    for (const m of muts) pending.add(m.type === 'childList' ? m.target : m.target)
    if (!queued) {
      queued = true
      window.setTimeout(flush, 40)
    }
  })
  walk(root)
  obs.observe(root, opts)
}
