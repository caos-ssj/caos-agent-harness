import React, { useState, useEffect } from 'react'
import {
  Terminal,
  Server,
  BarChart3,
  Shield,
  Layers,
  FolderGit2,
  X,
  Search,
  Check,
} from 'lucide-react'

interface CommandPaletteModalProps {
  isOpen: boolean
  onClose: () => void
  onSelectTab: (tab: 'console' | 'workstation' | 'providers' | 'stats' | 'skills') => void
  onSelectRepo: (repo: string) => void
  repositories: Array<{ name: string; path: string }>
  activeRepo: string
}

export const CommandPaletteModal: React.FC<CommandPaletteModalProps> = ({
  isOpen,
  onClose,
  onSelectTab,
  onSelectRepo,
  repositories,
  activeRepo,
}) => {
  const [search, setSearch] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  if (!isOpen) return null

  const actions = [
    {
      category: 'Go to',
      items: [
        { id: 'tab-console', label: 'Console', icon: Terminal, action: () => onSelectTab('console') },
        { id: 'tab-workstation', label: 'Board', icon: Layers, action: () => onSelectTab('workstation') },
        { id: 'tab-providers', label: 'Providers', icon: Server, action: () => onSelectTab('providers') },
        { id: 'tab-stats', label: 'Measured', icon: BarChart3, action: () => onSelectTab('stats') },
        { id: 'tab-skills', label: 'Skills', icon: Shield, action: () => onSelectTab('skills') },
      ],
    },
    {
      category: 'Workspace',
      items: repositories.map((r) => ({
        id: `repo-${r.name}`,
        label: `Repositorio: ${r.name}`,
        icon: FolderGit2,
        action: () => onSelectRepo(r.name),
        isCurrent: r.name === activeRepo,
      })),
    },
  ]

  const filteredCategories = actions
    .map((cat) => ({
      ...cat,
      items: cat.items.filter((item) =>
        item.label.toLowerCase().includes(search.toLowerCase()),
      ),
    }))
    .filter((cat) => cat.items.length > 0)
  const filteredItems = filteredCategories.flatMap((category) => category.items)

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/80 backdrop-blur-sm p-4">
      <div role="dialog" aria-modal="true" aria-label="Command palette" className="palette-panel work-surface border border-caos-borde bg-caos-tinta w-full max-w-xl shadow-2xl overflow-hidden flex flex-col">
        {/* Input de búsqueda */}
        <div className="p-3.5 border-b border-caos-borde bg-caos-negro flex items-center gap-3">
          <Search className="w-4 h-4 text-caos-tenue shrink-0" />
          <input
            type="text"
            aria-label="Search commands"
            autoFocus
            placeholder="Type a command or a view (Esc to close)"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setSelectedIndex(0) }}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown' && filteredItems.length) { e.preventDefault(); setSelectedIndex((selectedIndex + 1) % filteredItems.length) }
              if (e.key === 'ArrowUp' && filteredItems.length) { e.preventDefault(); setSelectedIndex((selectedIndex - 1 + filteredItems.length) % filteredItems.length) }
              if (e.key === 'Enter' && filteredItems[selectedIndex]) { e.preventDefault(); filteredItems[selectedIndex].action(); onClose() }
            }}
            className="flex-1 bg-transparent text-sm text-caos-hueso placeholder:text-caos-tenue focus:outline-none"
          />
          <button
            onClick={onClose}
            aria-label="Close palette"
            className="p-1 text-caos-tenue hover:text-caos-hueso cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Lista de Acciones */}
        <div className="max-h-96 overflow-y-auto p-2 divide-y divide-caos-borde/40">
          {filteredCategories.length === 0 ? (
            <div className="p-8 text-center text-xs text-caos-tenue font-mono">
              No command matches "{search}"
            </div>
          ) : (
            filteredCategories.map((cat) => (
              <div key={cat.category} className="py-2">
                <div className="px-3 py-1 text-[10px] uppercase font-bold text-caos-tenue font-mono">
                  {cat.category}
                </div>
                <div className="space-y-0.5 mt-1">
                  {cat.items.map((item: any) => {
                    const Icon = item.icon
                    return (
                      <button
                        key={item.id}
                        onClick={() => {
                          item.action()
                          onClose()
                        }}
                        onMouseEnter={() => setSelectedIndex(filteredItems.findIndex((result) => result.id === item.id))}
                        className={`w-full px-3 py-2 text-left text-xs text-caos-hueso hover:bg-caos-tintaElevada hover:text-caos-ambar flex items-center justify-between gap-3 transition-colors cursor-pointer ${filteredItems[selectedIndex]?.id === item.id ? 'bg-caos-tintaElevada' : ''}`}
                      >
                        <div className="flex items-center gap-2.5">
                          <Icon className="w-4 h-4 text-caos-tenue" />
                          <span>{item.label}</span>
                        </div>
                        {item.isCurrent && (
                          <span className="text-[10px] text-caos-greenText flex items-center gap-1 font-mono">
                            <Check className="w-3 h-3" />
                            <span>Actual</span>
                          </span>
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Pie con atajos */}
        <div className="border-t border-caos-borde p-2 bg-caos-negro flex items-center justify-between text-[11px] font-mono text-caos-tenue px-3">
          <span>↑ ↓ navegar · Enter abrir</span>
          <span>Esc cerrar</span>
        </div>
      </div>
    </div>
  )
}
