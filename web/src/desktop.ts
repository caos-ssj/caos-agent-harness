import { setBackendConnection } from './api'

export interface BackendInfo {
  port: number
  url: string
  token: string
  workspace?: string | null
}

export interface TraySyncState {
  project: string
  needsYou: number
  running: boolean
}

export function isDesktop(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export async function waitForDesktopBackend(): Promise<BackendInfo | null> {
  if (!isDesktop()) return null
  const { invoke } = await import('@tauri-apps/api/core')
  const info = await invoke<BackendInfo>('wait_for_backend')
  setBackendConnection(info.url, info.token)
  return info
}

export async function restartDesktopBackend(workspace?: string): Promise<BackendInfo | null> {
  if (!isDesktop()) return null
  const { invoke } = await import('@tauri-apps/api/core')
  const info = await invoke<BackendInfo>('restart_backend', { workspace: workspace ?? null })
  setBackendConnection(info.url, info.token)
  return info
}

export async function pickWorkspaceFolder(defaultPath?: string): Promise<string | null> {
  if (!isDesktop()) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const chosen = await open({
    directory: true,
    multiple: false,
    defaultPath,
    title: 'Seleccionar carpeta de proyecto CAOS',
  })
  return typeof chosen === 'string' && chosen.trim() ? chosen : null
}

export async function notifyDesktop(title: string, body: string): Promise<void> {
  if (isDesktop()) {
    try {
      const mod = await import('@tauri-apps/plugin-notification')
      let ok = await mod.isPermissionGranted()
      if (!ok) ok = (await mod.requestPermission()) === 'granted'
      if (ok) mod.sendNotification({ title, body })
      return
    } catch {
      /* fallback below */
    }
  }
  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
    try {
      new Notification(title, { body })
    } catch {
      /* ignore */
    }
  }
}

export async function syncTrayState(state: TraySyncState): Promise<void> {
  if (!isDesktop()) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('update_tray_state', {
      project: state.project,
      needsYou: state.needsYou,
      running: state.running,
    })
  } catch {
    /* ignore in headless/test */
  }
}

export async function openInFileManager(path: string): Promise<void> {
  if (!isDesktop() || !path) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_in_file_manager', { path })
  } catch {
    /* ignore */
  }
}

export async function openInTerminal(path: string): Promise<void> {
  if (!isDesktop() || !path) return
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    await invoke('open_in_terminal', { path })
  } catch {
    /* ignore */
  }
}

export async function openExternalUrl(url: string): Promise<void> {
  if (!isDesktop()) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  try {
    const { openUrl } = await import('@tauri-apps/plugin-opener')
    await openUrl(url)
  } catch {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

export async function onDesktopNavigate(onView: (view: string) => void): Promise<() => void> {
  if (!isDesktop()) return () => undefined
  try {
    const { listen } = await import('@tauri-apps/api/event')
    const unlisten = await listen<string>('caos://navigate', (event) => {
      if (typeof event.payload === 'string' && event.payload) onView(event.payload)
    })
    return unlisten
  } catch {
    return () => undefined
  }
}

/** The engine process died after it had been ready (crash or kill). Not fired for deliberate restarts or quitting. */
export async function onBackendExit(onExit: (detail: string) => void): Promise<() => void> {
  if (!isDesktop()) return () => undefined
  try {
    const { listen } = await import('@tauri-apps/api/event')
    return await listen<string>('caos://backend-exit', (event) => onExit(typeof event.payload === 'string' ? event.payload : ''))
  } catch {
    return () => undefined
  }
}
