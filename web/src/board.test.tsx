import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Board } from './components/Board'
import { composeReason, cleanQuote, QUOTE_MAX } from './components/ReviewNotes'
import { api, Agent, StateResponse, Task } from './api'

const task = (id: number, over: Partial<Task>): Task => ({
  id, text: `task ${id}`, state: 'pending', status: 'pending', queue: 'claude', agent: null, skill: null, created: 1700000000 + id, sent_at: null,
  review: null, review_note: null, reviewed_at: null, delivered: false, parent_id: null, criteria: null, worktree_key: null, position: id, effort: null, ...over,
})
const agent = (name: string, over: Partial<Agent> = {}): Agent => ({
  name, system: null, command: `${name} -p`, timeout: 600, pending: 0, working: 0, effort: null,
  effort_support: { supported: name === 'claude', reason: name === 'claude' ? 'sent as claude --effort <level>' : 'Ollama models have no effort setting' }, ...over,
})
const stateOf = (tasks: Task[], over: Partial<StateResponse> = {}): StateResponse => ({
  project: 'demo', root: '/tmp/demo', now: 1700001000, agents: [agent('claude'), agent('local', { command: 'ollama run x' })], tasks,
  stats: { tasks: tasks.length, by_status: {}, review: {}, returned_at_least_once: 0, by_agent: {} }, running: false, running_tasks: [], last_run: [], skills: [], tiers: [], ...over,
} as StateResponse)

const draw = (state: StateResponse, selectedId: number | null = null) => {
  const onChanged = vi.fn(), onSelect = vi.fn()
  render(<Board router={null} state={state} selectedId={selectedId} onSelect={onSelect} onChanged={onChanged} onRun={vi.fn()} runnable={1} filter={null} onFilter={vi.fn()} />)
  return { onChanged, onSelect }
}

describe('review notes', () => {
  it('composes one reason: the general note, then a line per quoted note', () => {
    const notes = [{ id: 1, quote: 'total 12', note: ' the total is 14 ', from: 'text' as const }, { id: 2, quote: '+ x = 1', note: '', from: 'diff' as const }]
    expect(composeReason('  overall close ', notes)).toBe('overall close\n“total 12” → the total is 14\n“+ x = 1”')
    expect(composeReason('', [])).toBe('')
    expect(cleanQuote('a\n  b\tc')).toBe('a b c')
    expect(cleanQuote('x'.repeat(500))).toHaveLength(QUOTE_MAX)
  })
})

describe('Board', () => {
  beforeEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })

  it('turns selected text of a delivery into notes and returns them together as one redo', async () => {
    const t = task(7, { state: 'to_review', status: 'sent', delivered: true, agent: 'claude' })
    vi.spyOn(api, 'getTask').mockResolvedValue({ ...t, result: 'The total is 12 units.\nTODO finish', timeline: [] })
    const review = vi.spyOn(api, 'reviewTask').mockResolvedValue({ id: 7, verdict: 'redo' })
    const { onChanged } = draw(stateOf([t]), 7)
    const pre = await screen.findByText(/The total is 12 units/)
    const select = (start: number, end: number) => {
      const r = document.createRange()
      r.setStart(pre.firstChild!, start); r.setEnd(pre.firstChild!, end)
      const s = window.getSelection()!
      s.removeAllRanges(); s.addRange(r)
      fireEvent(document, new Event('selectionchange'))
    }
    select(4, 15)
    fireEvent.click(await screen.findByRole('button', { name: 'Anotar el texto seleccionado' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Nota 1: qué corregir' }), { target: { value: 'it is 14' } })
    select(23, 27)
    fireEvent.click(await screen.findByRole('button', { name: 'Anotar el texto seleccionado' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Nota 2: qué corregir' }), { target: { value: 'finish it' } })
    select(0, 3)
    fireEvent.click(await screen.findByRole('button', { name: 'Anotar el texto seleccionado' }))
    fireEvent.click(screen.getByRole('button', { name: 'Quitar la nota 3' }))        // a note can be taken back before sending
    expect(within(screen.getByRole('list', { name: 'Notas de esta revisión' })).getAllByRole('listitem')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: /Devolver con notas \(2\)/ }))
    await waitFor(() => expect(review).toHaveBeenCalledTimes(1))
    expect(review).toHaveBeenCalledWith(7, 'redo', '“total is 12” → it is 14\n“TODO” → finish it')
    expect(onChanged).toHaveBeenCalled()
    expect(await screen.findByText(/devuelta con 2 nota\(s\)/)).toBeInTheDocument()
  })

  it('runs one pending task alone, and says why it cannot while its agent is busy', async () => {
    const run = vi.spyOn(api, 'runTask').mockResolvedValue({ started: true, id: 2 })
    const { onChanged } = draw(stateOf([task(1, {}), task(2, {}), task(3, { queue: 'person', state: 'person' })]))
    const buttons = screen.getAllByRole('button', { name: /Ejecutar ahora/ })
    expect(buttons).toHaveLength(2)                                                     // not offered for the task that waits for a person
    fireEvent.click(buttons[1])
    await waitFor(() => expect(run).toHaveBeenCalledWith(2))
    expect(run).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    cleanup()
    draw(stateOf([task(1, {}), task(2, { state: 'sending', status: 'sending', agent: 'claude' })], { agents: [agent('claude', { working: 1 })] }))
    const only = screen.getByRole('button', { name: /Ejecutar ahora/ })
    expect(only).toBeDisabled()
    expect(only).toHaveAttribute('title', 'claude está ocupado con otra tarea')
  })

  it('reorders inside a queue from the keyboard and lists pending tasks in the order they will run', async () => {
    const reorder = vi.spyOn(api, 'reorderTask').mockResolvedValue({ id: 3, before: 1, moved: true })
    draw(stateOf([task(1, { position: 2 }), task(2, { position: 3 }), task(3, { position: 1 }), task(4, { queue: 'local' })]))
    const grips = screen.getAllByRole('button', { name: /^Reordenar #/ })
    expect(grips.map((g) => g.getAttribute('aria-label')!.slice(11, 13))).toEqual(['03', '01', '02', '04'])
    fireEvent.keyDown(grips[2], { key: 'ArrowUp', altKey: true })                       // #02 goes above #01
    await waitFor(() => expect(reorder).toHaveBeenCalledWith(2, 1))
    fireEvent.keyDown(grips[0], { key: 'ArrowDown', altKey: true })                     // #03 goes below #01: before #02
    await waitFor(() => expect(reorder).toHaveBeenCalledWith(3, 2))
    fireEvent.keyDown(grips[2], { key: 'ArrowDown', altKey: true })                     // #02 is last in its queue: #04 belongs to another one
    fireEvent.keyDown(grips[3], { key: 'ArrowUp', altKey: true })
    expect(reorder).toHaveBeenCalledTimes(2)
  })

  it('offers effort on a new task only where the agent takes it, and says why not otherwise', async () => {
    const add = vi.spyOn(api, 'addTask').mockResolvedValue({ id: 9, queue: 'claude', why: 'queue given' })
    draw(stateOf([task(1, {})]))
    fireEvent.click(screen.getByRole('button', { name: /Nueva tarea/ }))
    const effort = screen.getByRole('combobox', { name: 'Esfuerzo de esta tarea' })
    expect(effort).toBeEnabled()
    fireEvent.change(effort, { target: { value: 'high' } })
    fireEvent.change(screen.getByPlaceholderText('Describe la tarea concreta…'), { target: { value: 'think hard' } })
    fireEvent.click(screen.getByRole('button', { name: 'Crear' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith({ text: 'think hard', queue: 'claude', effort: 'high' }))
    fireEvent.click(screen.getByRole('button', { name: /Nueva tarea/ }))
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'local' } })
    expect(screen.getByRole('combobox', { name: 'Esfuerzo de esta tarea' })).toBeDisabled()
    expect(screen.getByText('Ollama models have no effort setting')).toBeInTheDocument()
  })
})
