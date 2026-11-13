import React, { useEffect } from 'react'
import { Prefs } from '../prefs'
import { View } from '../lib'
import { useDialog, usePresence } from '../hooks'
import { getLang, setLang } from '../i18n'

interface PreferencesProps {
  open: boolean
  prefs: Prefs
  onChange: (p: Partial<Prefs>) => void
  onReset: () => void
  onClose: () => void
}

const STARTS: Array<[View, string]> = [
  ['console', 'Console'],
  ['board', 'Board'],
  ['providers', 'Providers'],
  ['metrics', 'Metrics'],
]

export const Preferences: React.FC<PreferencesProps> = ({ open, prefs, onChange, onReset, onClose }) => {
  const pres = usePresence(open, 150)
  const ref = useDialog<HTMLDivElement>(open, onClose, { initial: 'button[aria-pressed="true"]' })
  useEffect(() => {
    if (!open) return
    const click = (e: MouseEvent) => {
      const t = e.target as HTMLElement
      if (ref.current && !ref.current.contains(t) && !t.closest('[aria-haspopup="dialog"]')) onClose()
    }
    window.addEventListener('mousedown', click)
    return () => window.removeEventListener('mousedown', click)
  }, [open, onClose, ref])

  if (!pres.mounted) return null
  return (
    <div className="pop" role="dialog" aria-label="Preferences" ref={ref} data-leaving={pres.leaving ? '' : undefined}>
      <h2>Preferencias</h2>
      <fieldset>
        <legend>Language · Idioma</legend>
        <div className="seg">
          <button type="button" aria-pressed={getLang() === 'en'} onClick={() => getLang() !== 'en' && setLang('en')}>English</button>
          <button type="button" aria-pressed={getLang() === 'es'} onClick={() => getLang() !== 'es' && setLang('es')}>Español</button>
        </div>
      </fieldset>
      <fieldset>
        <legend>Densidad</legend>
        <div className="seg">
          <button type="button" aria-pressed={prefs.density === 'compact'} onClick={() => onChange({ density: 'compact' })}>Compacta</button>
          <button type="button" aria-pressed={prefs.density === 'comfortable'} onClick={() => onChange({ density: 'comfortable' })}>Cómoda</button>
        </div>
      </fieldset>
      <fieldset>
        <legend>Texto</legend>
        <div className="seg">
          <button type="button" aria-pressed={prefs.text === 'standard'} onClick={() => onChange({ text: 'standard' })}>Estándar</button>
          <button type="button" aria-pressed={prefs.text === 'large'} onClick={() => onChange({ text: 'large' })}>Grande</button>
        </div>
      </fieldset>
      <fieldset>
        <legend>Abrir en</legend>
        <div className="seg">
          {STARTS.map(([v, label]) => (
            <button key={v} type="button" aria-pressed={prefs.start === v} onClick={() => onChange({ start: v })}>
              {label}
            </button>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Perfil de enrutamiento</legend>
        <div className="seg" role="group" aria-label="Perfil de enrutamiento">
          <button type="button" aria-pressed={prefs.profile === 'local-first'} onClick={() => onChange({ profile: 'local-first' })} title="Privacidad y sin conexión: usa modelos locales mientras alguno responda">Local primero</button>
          <button type="button" aria-pressed={prefs.profile === 'hybrid'} onClick={() => onChange({ profile: 'hybrid' })} title="Cada intención va donde rinde mejor">Híbrido</button>
          <button type="button" aria-pressed={prefs.profile === 'cloud-max'} onClick={() => onChange({ profile: 'cloud-max' })} title="El mejor proveedor de nube conectado">Máx. nube</button>
        </div>
        <p className="pref-note">Decide qué modelo elige «Auto Intent» en Console.</p>
      </fieldset>
      <fieldset>
        <legend>Animaciones</legend>
        <div className="seg" role="group" aria-label="Animaciones">
          <button type="button" aria-pressed={prefs.motion === 'fluid'} onClick={() => onChange({ motion: 'fluid' })}>Fluido</button>
          <button type="button" aria-pressed={prefs.motion === 'focus'} onClick={() => onChange({ motion: 'focus' })} title="Sin movimiento decorativo">Enfoque</button>
        </div>
      </fieldset>
      <fieldset>
        <legend>Inspector de Console</legend>
        <label className="ws-check">
          <input type="checkbox" checked={prefs.inspector} onChange={(e) => onChange({ inspector: e.target.checked })} />
          Abierto por defecto (en pantallas anchas)
        </label>
      </fieldset>
      <fieldset>
        <legend>Notificaciones</legend>
        <label className="ws-check">
          <input
            type="checkbox"
            checked={prefs.notify}
            onChange={async (e) => {
              const on = e.target.checked
              if (on && 'Notification' in window && Notification.permission === 'default') {
                try {
                  await Notification.requestPermission()
                } catch {
                  /* ignore */
                }
              }
              onChange({ notify: on && 'Notification' in window && Notification.permission === 'granted' })
            }}
          />
          Avisar cuando llegue una entrega a revisar
        </label>
      </fieldset>
      <div className="pop-foot">
        <span>guardado en este navegador</span>
        <button type="button" className="btn btn-quiet btn-sm" onClick={onReset}>Restablecer</button>
      </div>
    </div>
  )
}
