// webapp/src/components/mobile/SuggestionChips.tsx
import { useState } from 'react'

interface SuggestionChipsProps {
  onSelect: (text: string) => void
  disabled?: boolean
  chips: readonly string[]
}

export function SuggestionChips({ onSelect, disabled = false, chips }: SuggestionChipsProps) {
  const [activeChip, setActiveChip] = useState<string | null>(null)

  const handleTap = (chip: string) => {
    if (disabled) return
    setActiveChip(chip)
    onSelect(chip)
  }

  return (
    <div className="flex gap-2 overflow-x-auto no-scrollbar" style={{ paddingBottom: 2 }}>
      {chips.map(chip => {
        const isActive = activeChip === chip
        return (
          <button
            key={chip}
            data-testid="starter-prompt"
            onClick={() => handleTap(chip)}
            disabled={disabled}
            className="flex-none h-8 px-3 rounded-full whitespace-nowrap transition-colors disabled:opacity-50 cursor-pointer"
            style={{
              border: isActive
                ? '1px solid rgba(72,246,193,0.60)'
                : '1px solid rgba(28,70,89,0.60)',
              background: isActive
                ? 'rgba(72,246,193,0.10)'
                : 'rgba(10,29,39,0.60)',
              color: isActive ? '#48F6C1' : '#85A4B1',
              fontFamily: 'var(--font-sans)',
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            {chip}
          </button>
        )
      })}
    </div>
  )
}
