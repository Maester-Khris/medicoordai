// webapp/src/components/mobile/TransitModeGrid.tsx
import { Car, Bicycle, Person } from '@phosphor-icons/react'
import type { RouteResult, TravelModeKey } from '@shared/types'
import { useConfig } from '../../hooks/useConfig'

export type TransitMode = 'drive' | 'cycle' | 'walk'

interface TransitCell {
  mode: TransitMode
  Icon: typeof Car
  label: string
}

const CELLS: TransitCell[] = [
  { mode: 'drive', Icon: Car,     label: 'DRIVE' },
  { mode: 'cycle', Icon: Bicycle, label: 'CYCLE' },
  { mode: 'walk',  Icon: Person,  label: 'WALK'  },
]

const MODE_KEY: Record<TransitMode, TravelModeKey> = { drive: 'car', cycle: 'bike', walk: 'walk' }

const CELL_STYLE: Record<TransitMode, { bg: string; border: string; color: string }> = {
  drive: { bg: 'rgba(72,246,193,0.15)',  border: 'rgba(72,246,193,0.60)',  color: '#48F6C1' },
  cycle: { bg: 'rgba(0,210,255,0.10)',   border: 'rgba(0,210,255,0.40)',   color: '#00D2FF' },
  walk: { bg: 'rgba(28,70,89,0.30)',    border: 'rgba(28,70,89,0.50)',    color: '#85A4B1' },
}

interface TransitModeGridProps {
  routes: RouteResult[]
  activeMode: TransitMode
  onModeChange: (mode: TransitMode) => void
}

export function TransitModeGrid({ routes, activeMode, onModeChange }: TransitModeGridProps) {
  const config = useConfig()
  const cells = CELLS.filter(cell => config.modes_enabled.includes(MODE_KEY[cell.mode]))
  const driveRoute = routes[0]

  const getEta = (mode: TransitMode): string => {
    if (mode === 'drive' && driveRoute) return `${driveRoute.etaMinutes}min`
    if (mode === 'cycle' && driveRoute) return `${Math.round(driveRoute.etaMinutes * 2.5)}min`
    if (mode === 'walk'  && driveRoute) return `${Math.round(driveRoute.etaMinutes * 6)}min`
    return '—'
  }

  return (
    <div className="grid gap-2 mt-3" style={{ gridTemplateColumns: `repeat(${cells.length}, minmax(0, 1fr))` }}>
      {cells.map(({ mode, Icon, label }) => {
        const isActive = activeMode === mode
        const style = isActive ? CELL_STYLE[mode] : CELL_STYLE.walk
        return (
          <button
            key={mode}
            onClick={() => onModeChange(mode)}
            className="flex flex-col items-center justify-center gap-1 rounded-xl cursor-pointer border-none"
            style={{
              height: 56,
              background: style.bg,
              border: `1px solid ${style.border}`,
            }}
          >
            <Icon size={20} color={style.color} />
            <span className="font-mono text-[11px] font-bold" style={{ color: style.color }}>
              {getEta(mode)}
            </span>
            <span className="font-mono text-[9px] uppercase tracking-wide" style={{ color: style.color }}>
              {label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
