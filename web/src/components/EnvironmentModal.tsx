import React from 'react'
import { X, Palette, Sparkles, Check, Sliders, LayoutGrid } from 'lucide-react'

export interface EnvironmentSettings {
  accent: 'ambar' | 'esmeralda' | 'platino' | 'cian'
  pattern: 'obsidian' | 'vignette'
  density: 'comfortable' | 'compact'
}

interface EnvironmentModalProps {
  isOpen: boolean
  onClose: () => void
  settings: EnvironmentSettings
  onUpdateSettings: (newSettings: Partial<EnvironmentSettings>) => void
}

export const EnvironmentModal: React.FC<EnvironmentModalProps> = ({
  isOpen,
  onClose,
  settings,
  onUpdateSettings,
}) => {
  if (!isOpen) return null

  const accents: Array<{ id: EnvironmentSettings['accent']; label: string; preview: string; desc: string }> = [
    {
      id: 'ambar',
      label: 'Amber (house)',
      preview: '#C9975C',
      desc: 'The house accent: a quiet warm amber.',
    },
    {
      id: 'esmeralda',
      label: 'Verde Esmeralda Evidencia',
      preview: '#10B981',
      desc: 'Inspirado en la suite de QA y pruebas superadas al 100%.',
    },
    {
      id: 'platino',
      label: 'Silver',
      preview: '#E7E3DE',
      desc: 'Monocromo de alto contraste con filo de acero pulido.',
    },
    {
      id: 'cian',
      label: 'Cyan',
      preview: '#38BDF8',
      desc: 'A colder, instrument-like contrast.',
    },
  ]

  const patterns: Array<{ id: EnvironmentSettings['pattern']; label: string; desc: string }> = [
    {
      id: 'obsidian',
      label: 'Obsidiana Profundo (#060607)',
      desc: 'Plain house black.',
    },
    {
      id: 'vignette',
      label: 'Night vignette',
      desc: 'Light falls off towards the edges.',
    },
  ]

  const densities: Array<{ id: EnvironmentSettings['density']; label: string; desc: string }> = [
    {
      id: 'comfortable',
      label: 'Respirable Equilibrado',
      desc: 'Espaciado pulido para sesiones de trabajo prolongadas.',
    },
    {
      id: 'compact',
      label: 'Compacto Hacker Pro',
      desc: 'More rows on a laptop screen.',
    },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="w-full max-w-lg border border-caos-borde bg-caos-negro shadow-2xl flex flex-col overflow-hidden">
        {/* Cabecera del modal */}
        <div className="border-b border-caos-borde p-4 bg-caos-tinta flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Palette className="w-4 h-4 text-caos-ambar" />
            <h3 className="font-serif text-lg text-caos-hueso font-bold tracking-wide">
              Appearance
            </h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-caos-tenue hover:text-caos-hueso border border-caos-borde bg-caos-negro transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Cuerpo de opciones */}
        <div className="p-5 space-y-6 max-h-[75vh] overflow-y-auto">
          {/* 1. Tono de Acento */}
          <div>
            <label className="text-xs font-mono font-bold text-caos-champan uppercase tracking-wider block mb-2.5 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-caos-ambar" />
              <span>Accent</span>
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {accents.map((acc) => (
                <button
                  key={acc.id}
                  type="button"
                  onClick={() => onUpdateSettings({ accent: acc.id })}
                  className={`p-3 border text-left flex items-start gap-3 transition-all cursor-pointer ${
                    settings.accent === acc.id
                      ? 'border-caos-ambar bg-caos-tinta shadow-md'
                      : 'border-caos-borde bg-caos-negro hover:border-caos-bordeLight'
                  }`}
                >
                  <span
                    className="w-4 h-4 rounded-none shrink-0 mt-0.5 border border-white/20"
                    style={{ backgroundColor: acc.preview }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold text-caos-hueso flex items-center justify-between">
                      <span>{acc.label}</span>
                      {settings.accent === acc.id && (
                        <Check className="w-3.5 h-3.5 text-caos-ambar shrink-0 ml-1" />
                      )}
                    </div>
                    <p className="text-[11px] text-caos-tenue mt-0.5 leading-snug">
                      {acc.desc}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* 2. Textura de Fondo y Atmósfera */}
          <div>
            <label className="text-xs font-mono font-bold text-caos-champan uppercase tracking-wider block mb-2.5 flex items-center gap-1.5">
              <LayoutGrid className="w-3.5 h-3.5 text-caos-ambar" />
              <span>Background</span>
            </label>
            <div className="space-y-2">
              {patterns.map((pat) => (
                <button
                  key={pat.id}
                  type="button"
                  onClick={() => onUpdateSettings({ pattern: pat.id })}
                  className={`w-full p-3 border text-left flex items-center justify-between transition-all cursor-pointer ${
                    settings.pattern === pat.id
                      ? 'border-caos-ambar bg-caos-tinta shadow-md'
                      : 'border-caos-borde bg-caos-negro hover:border-caos-bordeLight'
                  }`}
                >
                  <div>
                    <div className="text-xs font-bold text-caos-hueso">{pat.label}</div>
                    <div className="text-[11px] text-caos-tenue mt-0.5">{pat.desc}</div>
                  </div>
                  {settings.pattern === pat.id && (
                    <Check className="w-4 h-4 text-caos-ambar shrink-0" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* 3. Densidad Visual */}
          <div>
            <label className="text-xs font-mono font-bold text-caos-champan uppercase tracking-wider block mb-2.5 flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-caos-ambar" />
              <span>Density</span>
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              {densities.map((den) => (
                <button
                  key={den.id}
                  type="button"
                  onClick={() => onUpdateSettings({ density: den.id })}
                  className={`p-3 border text-left transition-all cursor-pointer ${
                    settings.density === den.id
                      ? 'border-caos-ambar bg-caos-tinta shadow-md'
                      : 'border-caos-borde bg-caos-negro hover:border-caos-bordeLight'
                  }`}
                >
                  <div className="text-xs font-bold text-caos-hueso flex items-center justify-between">
                    <span>{den.label}</span>
                    {settings.density === den.id && (
                      <Check className="w-3.5 h-3.5 text-caos-ambar shrink-0" />
                    )}
                  </div>
                  <div className="text-[11px] text-caos-tenue mt-1 leading-snug">
                    {den.desc}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Pie del modal */}
        <div className="border-t border-caos-borde p-3.5 bg-caos-tinta flex items-center justify-between text-xs font-mono text-caos-tenue">
          <span>Persistido en almacenamiento local</span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 border border-caos-ambar bg-caos-ambar text-caos-negro font-bold hover:bg-caos-champan transition-colors cursor-pointer text-xs uppercase"
          >
            Listo
          </button>
        </div>
      </div>
    </div>
  )
}
