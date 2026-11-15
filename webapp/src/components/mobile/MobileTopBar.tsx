// webapp/src/components/mobile/MobileTopBar.tsx
import { ListIcon } from '@phosphor-icons/react'
import type { Severity } from '@shared/types'
import { SEVERITY_LABEL } from '../../lib/severityLabels'

export type MobileMode = 'browse' | 'recommendation'

interface MobileTopBarProps {
  mode: MobileMode
  severity: Severity | null
  onMenuOpen?: () => void
}

const SEVERITY_CHIP: Record<Severity, { border: string; bg: string; text: string; label: string }> = {
  routine:  { border: 'rgba(0,210,255,0.6)',   bg: 'rgba(0,210,255,0.10)',   text: '#00D2FF', label: SEVERITY_LABEL.routine    },
  moderate: { border: 'rgba(0,210,255,0.6)',   bg: 'rgba(0,210,255,0.10)',   text: '#00D2FF', label: SEVERITY_LABEL.moderate },
  urgent:   { border: 'rgba(245,158,11,0.6)',  bg: 'rgba(245,158,11,0.10)',  text: '#F59E0B', label: SEVERITY_LABEL.urgent     },
  emergent: { border: 'rgba(255,123,147,0.6)', bg: 'rgba(255,123,147,0.10)', text: '#FF7B93', label: SEVERITY_LABEL.emergent   },
}

export function MobileTopBar({ mode, severity, onMenuOpen }: MobileTopBarProps) {
  const chip = severity ? SEVERITY_CHIP[severity] : null

  return (
    <header
      className="flex-none flex items-center justify-between px-4 z-50"
      style={{
        height: 56,
        position: 'fixed',
        top: 0, left: 0, right: 0,
        background: 'rgba(6,18,25,0.90)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(28,70,89,0.40)',
      }}
    >
      {/* Left — hamburger + wordmark as a single tap target */}
      <button
        onClick={onMenuOpen}
        className="flex items-center gap-2 bg-transparent border-none p-0 cursor-pointer"
        aria-label="Open menu"
      >
        <ListIcon size={20} color="#48F6C1" weight="bold" />
        <span
          className="font-bold text-[16px]"
          style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}
        >
          MediCoordAI
        </span>
      </button>

      {/* Right — ONLINE pill (State 1) or Severity Chip (State 2) */}
      {mode === 'browse' ? (
        <div
          className="flex items-center gap-1.5 px-3 py-1 rounded-full"
          style={{
            background: 'rgba(72,246,193,0.15)',
            border: '1px solid rgba(72,246,193,0.50)',
          }}
        >
          <span
            className="w-2 h-2 rounded-full animate-pulse"
            style={{ background: '#48F6C1' }}
          />
          <span
            className="font-mono text-[10px] font-bold tracking-widest"
            style={{ color: '#48F6C1' }}
          >
            ONLINE
          </span>
        </div>
      ) : (
        chip && (
          <div
            className="flex items-center px-[10px]"
            style={{
              height: 28,
              borderRadius: 999,
              border: `1px solid ${chip.border}`,
              background: chip.bg,
            }}
          >
            <span
              className="font-mono text-[10px] font-bold tracking-widest"
              style={{ color: chip.text }}
            >
              {chip.label}
            </span>
          </div>
        )
      )}
    </header>
  )
}
