import React from 'react'
import {
  Play,
  RefreshCw,
  Terminal,
  Layers,
  BarChart3,
  Server,
  Shield,
  Command,
  Palette,
} from 'lucide-react'
import { StateResponse } from '../api'

interface HeaderProps {
  state: StateResponse | null
  activeTab: 'console' | 'workstation' | 'providers' | 'stats' | 'skills'
  onSelectTab: (tab: 'console' | 'workstation' | 'providers' | 'stats' | 'skills') => void
  onRunPending: () => void
  isRefreshing: boolean
  onRefresh: () => void
  onOpenPalette: () => void
  onOpenEnvironment: () => void
  activeRepo: string
}

export const Header: React.FC<HeaderProps> = ({
  state,
  activeTab,
  onSelectTab,
  onRunPending,
  isRefreshing,
  onRefresh,
  onOpenPalette,
  onOpenEnvironment,
  activeRepo,
}) => {
  const pendingCount = state?.stats.by_status?.pending ?? 0
  const reviewCount = state?.tasks.filter((t) => t.state === 'person' || t.state === 'to_review').length ?? 0
  const isRunning = state?.running ?? false

  return (
    <header className="app-header h-14 shrink-0 border-b border-caos-borde bg-caos-tinta z-30 px-2 sm:px-4 flex items-center gap-2 select-none">
      {/* 1. Identidad de Marca CAOS y Selector de Repositorio */}
      <div className="flex items-center gap-4 shrink-0">
        <div className="flex items-center gap-2.5">
          <img src="/art/mark.svg" alt="CAOS Mark" className="w-6 h-6 opacity-90 drop-shadow" />
          <div className="flex items-baseline gap-2">
            <span className="font-brand text-2xl text-plata-metal tracking-wide leading-none">
              caos
            </span>
            <span className="hidden xl:inline text-[10px] uppercase tracking-widest text-caos-champan font-bold font-mono">
              HARNESS // 2026
            </span>
          </div>
        </div>

        {/* Separador vertical */}
        <span className="hidden sm:inline text-caos-borde text-sm">/</span>

        {/* Repo badge */}
        <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 border border-caos-borde bg-caos-negro text-[11px] font-mono">
          <span className="text-caos-tenue">repo:</span>
          <span className="text-caos-hueso font-bold">{activeRepo}</span>
        </div>
      </div>

      {/* 2. Pestañas de Navegación Principales (Centro) */}
      <nav aria-label="Main" className="flex flex-1 min-w-0 items-center gap-1 overflow-x-auto text-xs font-semibold whitespace-nowrap">
        <button
          onClick={() => onSelectTab('console')}
          className={`flex items-center gap-1.5 px-3 py-1.5 border transition-all cursor-pointer ${
            activeTab === 'console'
              ? 'border-caos-ambar bg-caos-negro text-caos-hueso shadow-sm'
              : 'border-transparent text-caos-gris hover:text-caos-hueso hover:bg-caos-negro/50'
          }`}
        >
          <Terminal className="w-3.5 h-3.5 text-caos-ambar" />
          <span>Console</span>
        </button>

        <button
          onClick={() => onSelectTab('workstation')}
          className={`flex items-center gap-1.5 px-3 py-1.5 border transition-all cursor-pointer ${
            activeTab === 'workstation'
              ? 'border-caos-ambar bg-caos-negro text-caos-hueso shadow-sm'
              : 'border-transparent text-caos-gris hover:text-caos-hueso hover:bg-caos-negro/50'
          }`}
        >
          <Layers className="w-3.5 h-3.5" />
          <span>Board</span>
          {reviewCount > 0 && (
            <span className="px-1.5 py-0.2 bg-caos-ambar text-caos-negro text-[10px] font-bold">
              {reviewCount}
            </span>
          )}
        </button>

        <button
          onClick={() => onSelectTab('providers')}
          className={`flex items-center gap-1.5 px-3 py-1.5 border transition-all cursor-pointer ${
            activeTab === 'providers'
              ? 'border-caos-ambar bg-caos-negro text-caos-hueso shadow-sm'
              : 'border-transparent text-caos-gris hover:text-caos-hueso hover:bg-caos-negro/50'
          }`}
        >
          <Server className="w-3.5 h-3.5" />
          <span>Providers</span>
        </button>

        <button
          onClick={() => onSelectTab('stats')}
          className={`flex items-center gap-1.5 px-3 py-1.5 border transition-all cursor-pointer ${
            activeTab === 'stats'
              ? 'border-caos-ambar bg-caos-negro text-caos-hueso shadow-sm'
              : 'border-transparent text-caos-gris hover:text-caos-hueso hover:bg-caos-negro/50'
          }`}
        >
          <BarChart3 className="w-3.5 h-3.5" />
          <span>Measured</span>
        </button>

        <button
          onClick={() => onSelectTab('skills')}
          className={`flex items-center gap-1.5 px-3 py-1.5 border transition-all cursor-pointer ${
            activeTab === 'skills'
              ? 'border-caos-ambar bg-caos-negro text-caos-hueso shadow-sm'
              : 'border-transparent text-caos-gris hover:text-caos-hueso hover:bg-caos-negro/50'
          }`}
        >
          <Shield className="w-3.5 h-3.5" />
          <span>Skills</span>
        </button>
      </nav>

      {/* 3. Acciones Rápidas de Cabecera (Derecha) */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Botón Personalización del Entorno */}
        <button
          onClick={onOpenEnvironment}
          aria-label="Appearance"
          title="Appearance: accent, background, density"
          className="p-1.5 border border-caos-borde bg-caos-negro text-caos-champan hover:text-caos-hueso hover:border-caos-ambar transition-colors cursor-pointer"
        >
          <Palette className="w-4 h-4 text-caos-ambar" />
        </button>

        {/* Atajo Paleta Ctrl+K */}
        <button
          onClick={onOpenPalette}
          title="Command palette (Ctrl+K)"
          className="flex items-center gap-1 px-2.5 py-1.5 border border-caos-borde bg-caos-negro text-caos-gris hover:text-caos-hueso hover:border-caos-ambar text-xs font-mono transition-colors cursor-pointer"
        >
          <Command className="w-3.5 h-3.5 text-caos-ambar" />
          <span>⌘K</span>
        </button>

        {/* Refrescar */}
        <button
          onClick={onRefresh}
          aria-label="Refresh"
          disabled={isRefreshing}
          title="Refresh"
          className="hidden sm:block p-1.5 border border-caos-borde bg-caos-negro text-caos-gris hover:text-caos-hueso transition-colors cursor-pointer"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-caos-ambar' : ''}`} />
        </button>

        {/* Botón Ejecutar Lote */}
        <button
          onClick={onRunPending}
          disabled={isRunning || pendingCount === 0}
          title={`Run pending tasks (${pendingCount})`}
          aria-label={`Run pending tasks (${pendingCount})`}
          className={`flex items-center gap-1.5 px-2 lg:px-3 py-1.5 border text-xs uppercase font-bold tracking-wider transition-all cursor-pointer ${
            pendingCount > 0
              ? 'border-caos-ambar text-caos-negro bg-caos-ambar hover:bg-caos-champan'
              : 'border-caos-borde text-caos-tenue bg-caos-negro cursor-not-allowed opacity-50'
          }`}
        >
          <Play className={`w-3.5 h-3.5 fill-current ${isRunning ? 'animate-pulse' : ''}`} />
          <span className="hidden lg:inline">Run ({pendingCount})</span>
        </button>
      </div>
    </header>
  )
}
