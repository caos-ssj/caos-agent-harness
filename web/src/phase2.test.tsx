import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { DiffViewer, splitRows, parseUnifiedDiff } from './components/DiffViewer'
import { DEFAULT_PREFS, readPrefs } from './prefs'
import { ago, stripAnsi } from './lib'
import { groupSkills } from './skillCats'

const DIFF = `diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,3 +1,3 @@
 keep
-old line
+new line
 tail
`

describe('prefs', () => {
  it('starts fluid with the inspector open, whatever the system asks, and keeps a saved choice', () => {
    expect(DEFAULT_PREFS).toMatchObject({ motion: 'fluid', inspector: true, profile: 'hybrid' })
    expect(readPrefs({})).toMatchObject({ motion: 'fluid', inspector: true })
    expect(readPrefs({ motion: 'focus', inspector: false, profile: 'cloud-max' })).toMatchObject({ motion: 'focus', inspector: false, profile: 'cloud-max' })
    expect(readPrefs({ motion: 'sparkly', profile: 'x' })).toMatchObject({ motion: 'fluid', profile: 'hybrid' })
  })
})

describe('helpers', () => {
  it('removes terminal escapes and tells time in Spanish', () => {
    expect(stripAnsi('\x1b[31mfail\x1b[0m ok\x1b]0;title\x07')).toBe('fail ok')
    expect(ago(1000, 1000 * 1000 + 5000)).toBe('ahora')
    expect(ago(1000, 1000 * 1000 + 600_000)).toBe('hace 10 min')
  })
  it('groups skills by category in the dashboard order and filters by name or category', () => {
    const skills = [{ name: 'writer', description: 'docs', category: 'Investigación & Docs' }, { name: 'coder', description: 'code', category: 'Código & Infra' }, { name: 'mine', description: 'x' }]
    expect(groupSkills(skills).map((g) => g.cat)).toEqual(['Código & Infra', 'Investigación & Docs', 'Proyecto'])
    expect(groupSkills(skills, 'docs').map((g) => g.items[0].name)).toEqual(['writer'])
  })
})

describe('DiffViewer', () => {
  beforeEach(() => { cleanup(); localStorage.clear() })

  it('pairs a removal with the addition that replaced it for the side-by-side view', () => {
    const rows = splitRows(parseUnifiedDiff(DIFF)[0].lines)
    const pair = rows.find((r) => r.left?.type === 'del')!
    expect(pair.left?.text).toBe('old line')
    expect(pair.right?.text).toBe('new line')
  })

  it('switches to Split and remembers it', () => {
    render(<DiffViewer diffText={DIFF} />)
    fireEvent.click(screen.getByRole('button', { name: /Split/ }))
    expect(document.querySelector('.diff-lines.is-split')).not.toBeNull()
    expect(localStorage.getItem('caos_diff_mode')).toBe('split')
  })

  it('collects comments in a tray and sends them together, not one by one', () => {
    const send = vi.fn()
    render(<DiffViewer diffText={DIFF} onSendDrafts={send} />)
    fireEvent.click(screen.getAllByRole('button', { name: /line 2/ })[0])
    fireEvent.change(screen.getByPlaceholderText(/Qué debe cambiar/), { target: { value: 'use a constant' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(send).not.toHaveBeenCalled()
    const tray = screen.getByRole('region', { name: 'Comentarios de revisión' })
    expect(within(tray).getByText(/Comentarios de revisión \(1\)/)).toBeInTheDocument()
    fireEvent.click(within(tray).getByRole('button', { name: /Enviar 1 al compositor/ }))
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][0]).toContain('[a.py:')
    expect(send.mock.calls[0][0]).toContain('→ use a constant')
  })

  it('keeps the old one-click citation when no tray is wanted', () => {
    const cite = vi.fn()
    render(<DiffViewer diffText={DIFF} onAnnotateLine={cite} />)
    fireEvent.click(screen.getAllByRole('button', { name: /line 2/ })[0])
    expect(cite).toHaveBeenCalledTimes(1)
  })
})
