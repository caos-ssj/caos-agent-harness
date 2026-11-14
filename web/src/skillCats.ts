import { SkillInfo } from './api'

export const CAT_ORDER = ['Código & Infra', 'QA & Testing', 'UI & Frontend', 'Modelos & Router', 'Investigación & Docs', 'Proyecto', 'Agencia']
export const CAT_ACCENT: Record<string, string> = {
  'Código & Infra': '#7FA6D6',
  'QA & Testing': '#6BC78E',
  'UI & Frontend': '#EBD3BB',
  'Modelos & Router': '#EB9D44',
  'Investigación & Docs': '#D4A36A',
  'Proyecto': '#F5F2EC',
  'Agencia': '#BBB3A8',
  'Planificar e Investigar': '#D4A36A',
  'Escribir Código': '#7FA6D6',
  'Auditar / QA': '#6BC78E',
  'Automatización y MCP': '#EB9D44',
}
export const catOf = (s: Pick<SkillInfo, 'category'>) => s.category || 'Proyecto'

/** Legacy category grouping used by unit test in phase2.test.tsx. */
export function groupSkills(skills: SkillInfo[], needle = ''): Array<{ cat: string; items: SkillInfo[] }> {
  const q = needle.trim().toLowerCase()
  const match = (s: SkillInfo) => !q || s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q) || catOf(s).toLowerCase().includes(q)
  const by = new Map<string, SkillInfo[]>()
  for (const s of skills.filter(match)) by.set(catOf(s), [...(by.get(catOf(s)) ?? []), s])
  const cats = [...by.keys()].sort((a, b) => (CAT_ORDER.indexOf(a) + 1 || 99) - (CAT_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b))
  return cats.map((cat) => ({ cat, items: by.get(cat)! }))
}

export const WORKFLOW_ORDER = [
  'Planificar e Investigar',
  'Escribir Código',
  'Auditar / QA',
  'Automatización y MCP',
] as const

export function workflowCatOf(s: Pick<SkillInfo, 'name' | 'category' | 'description'>): string {
  const n = s.name.toLowerCase()
  const c = (s.category || '').toLowerCase()
  if (/(qa|test|audit|verif)/.test(n) || c.includes('qa')) return 'Auditar / QA'
  if (/(codigo|code|impeccable|ui|front|generative)/.test(n) || c.includes('código') || c.includes('ui')) return 'Escribir Código'
  if (/(mcp|model|router|automa|plugin|gdrive|migrate|trading)/.test(n) || c.includes('modelo')) return 'Automatización y MCP'
  if (/(investig|context|doc-|convert|redact|propuest|conten|writer|guide|find-skills|customiz)/.test(n) || c.includes('investig') || c.includes('agencia')) return 'Planificar e Investigar'
  const d = (s.description || '').toLowerCase()
  if (/\b(qa|pytest|test|audit)\b/.test(d)) return 'Auditar / QA'
  if (/\b(mcp|ollama|router|plugin|automation)\b/.test(d)) return 'Automatización y MCP'
  if (/\b(investigar|research|document|notes|redes|propuesta)\b/.test(d)) return 'Planificar e Investigar'
  return 'Escribir Código'
}

/** Workflow-based skill grouping (4 clear stages). */
export function groupSkillsByWorkflow(skills: SkillInfo[], needle = ''): Array<{ cat: string; items: SkillInfo[] }> {
  const q = needle.trim().toLowerCase()
  const match = (s: SkillInfo) =>
    !q ||
    s.name.toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q) ||
    workflowCatOf(s).toLowerCase().includes(q) ||
    catOf(s).toLowerCase().includes(q)
  const by = new Map<string, SkillInfo[]>()
  for (const s of skills.filter(match)) {
    const w = workflowCatOf(s)
    by.set(w, [...(by.get(w) ?? []), s])
  }
  const cats = [...by.keys()].sort((a, b) => (WORKFLOW_ORDER.indexOf(a as any) + 1 || 99) - (WORKFLOW_ORDER.indexOf(b as any) + 1 || 99))
  return cats.map((cat) => ({ cat, items: by.get(cat)! }))
}
