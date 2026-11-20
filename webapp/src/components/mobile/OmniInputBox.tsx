// webapp/src/components/mobile/OmniInputBox.tsx
import { Microphone, ArrowRight } from '@phosphor-icons/react'

interface OmniInputBoxProps {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  disabled?: boolean
}

export function OmniInputBox({ value, onChange, onSend, disabled = false }: OmniInputBoxProps) {
  const canSend = !disabled && value.trim().length > 0

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (canSend) onSend()
    }
  }

  return (
    <div
      className="flex items-center gap-2 px-4"
      style={{
        height: 52,
        borderRadius: 12,
        border: '1px solid rgba(28,70,89,0.65)',
        background: 'rgba(6,18,25,0.80)',
        backdropFilter: 'blur(4px)',
      }}
    >
      <Microphone size={18} color="#85A4B1" />
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={1}
        placeholder="Describe your symptoms..."
        className="flex-1 bg-transparent resize-none text-[16px] focus:outline-none leading-5 no-scrollbar border-none outline-none"
        style={{
          color: '#E2F1F5',
          minHeight: 24,
        }}
      />
      <button
        onClick={onSend}
        disabled={!canSend}
        className="flex items-center justify-center flex-none transition-transform active:scale-95 border-none cursor-pointer"
        style={{
          width: 44,
          height: 44,
          borderRadius: 8,
          background: canSend ? '#48F6C1' : 'rgba(28,70,89,0.5)',
        }}
        aria-label="Send"
      >
        <ArrowRight size={16} color={canSend ? '#061219' : '#85A4B1'} weight="bold" />
      </button>
    </div>
  )
}
