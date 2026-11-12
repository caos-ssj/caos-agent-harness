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
}
export const catOf = (s: Pick<SkillInfo, 'category'>) => s.category || 'Proyecto'

/** Skills grouped by category, in the order the dashboard shows them; unknown categories follow. */
export function groupSkills(skills: SkillInfo[], needle = ''): Array<{ cat: string; items: SkillInfo[] }> {
  const q = needle.trim().toLowerCase()
  const match = (s: SkillInfo) => !q || s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q) || catOf(s).toLowerCase().includes(q)
  const by = new Map<string, SkillInfo[]>()
  for (const s of skills.filter(match)) by.set(catOf(s), [...(by.get(catOf(s)) ?? []), s])
  const cats = [...by.keys()].sort((a, b) => (CAT_ORDER.indexOf(a) + 1 || 99) - (CAT_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b))
  return cats.map((cat) => ({ cat, items: by.get(cat)! }))
}
