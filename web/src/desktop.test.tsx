import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { App } from './App'
import { apiUrl, setBackendConnection } from './api'

describe('desktop runtime bridge', () => {
  beforeEach(() => {
    setBackendConnection('', null)
    delete (window as any).__TAURI_INTERNALS__
  })
  afterEach(() => {
    setBackendConnection('', null)
    delete (window as any).__TAURI_INTERNALS__
    vi.restoreAllMocks()
  })

  it('builds relative URLs in browser mode and tokenized loopback URLs in desktop mode', () => {
    expect(apiUrl('/api/events', true)).toBe('/api/events')
    setBackendConnection('http://127.0.0.1:44321/', 'tok+1')
    expect(apiUrl('/api/state')).toBe('http://127.0.0.1:44321/api/state')
    expect(apiUrl('/api/events', true)).toBe('http://127.0.0.1:44321/api/events?token=tok%2B1')
    expect(apiUrl('/api/share/download?file=pack.zip', true)).toBe(
      'http://127.0.0.1:44321/api/share/download?file=pack.zip&token=tok%2B1',
    )
  })

  it('shows desktop boot screen and retry button if the local sidecar fails to start', async () => {
    (window as any).__TAURI_INTERNALS__ = {
      invoke: vi.fn().mockRejectedValue(new Error('python runtime not found')),
    }
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText('Error iniciando motor local')).toBeInTheDocument()
      expect(screen.getByText(/python runtime not found/)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Reintentar arranque' })).toBeInTheDocument()
    })
  })

  it('retry starts a fresh engine through restart_backend instead of re-waiting on the dead one', async () => {
    const calls: string[] = []
    const invoke = vi.fn(async (cmd: string) => {
      calls.push(cmd)
      if (cmd === 'wait_for_backend') throw new Error('boom')
      if (cmd === 'restart_backend') return { port: 4321, url: 'http://127.0.0.1:4321', token: 't', workspace: null }
      return undefined
    })
    ;(window as any).__TAURI_INTERNALS__ = { invoke }
    render(<App />)
    const retry = await screen.findByRole('button', { name: 'Reintentar arranque' })
    retry.click()
    await waitFor(() => expect(calls).toContain('restart_backend'))
  })
})
