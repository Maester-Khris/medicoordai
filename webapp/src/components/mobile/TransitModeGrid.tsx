// webapp/src/components/mobile/TransitModeGrid.tsx
import { Bicycle, Bus, Car, Person } from '@phosphor-icons/react'
import type { TravelModeKey } from '@shared/types'
import { useConfig } from '../../hooks/useConfig'

interface ModeCell {
  mode: TravelModeKey
  Icon: typeof Car
  label: string
}

const CELLS: ModeCell[] = [
  { mode: 'car',  Icon: Car,     label: 'DRIVE' },
  { mode: 'bike', Icon: Bicycle, label: 'CYCLE' },
  { mode: 'bus',  Icon: Bus,     label: 'TRANSIT' },
  { mode: 'walk', Icon: Person,  label: 'WALK' },
]

const ACTIVE_STYLE = { bg: 'rgba(72,246,193,0.15)', border: 'rgba(72,246,193,0.60)', color: '#48F6C1' }
const IDLE_STYLE = { bg: 'rgba(28,70,89,0.30)', border: 'rgba(28,70,89,0.50)', color: '#85A4B1' }

interface TransitModeGridProps {
  /** Travel time of the recommended facility for the active mode; null while unknown. */
  etaMinutes: number | null
  activeMode: TravelModeKey
  loading: boolean
  onModeChange: (mode: TravelModeKey) => void
}

export function TransitModeGrid({ etaMinutes, activeMode, loading, onModeChange }: TransitModeGridProps) {
  const config = useConfig()
  const cells = CELLS.filter(cell => config.modes_enabled.includes(cell.mode))

  return (
    <div className="grid gap-2 mt-3" style={{ gridTemplateColumns: `repeat(${cells.length}, minmax(0, 1fr))` }}>
      {cells.map(({ mode, Icon, label }) => {
        const isActive = activeMode === mode
        const style = isActive ? ACTIVE_STYLE : IDLE_STYLE
        return (
          <button
            key={mode}
            type="button"
            data-testid={`card-mode-${mode}`}
            aria-pressed={isActive}
            aria-busy={isActive && loading}
            disabled={loading}
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
              {isActive && etaMinutes !== null ? `${etaMinutes}min` : '—'}
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
