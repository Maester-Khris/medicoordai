// webapp/src/components/mobile/BottomSheet.tsx
import { useEffect, useRef, type ReactNode } from 'react'
import { motion, type PanInfo } from 'motion/react'
import type { Message } from '@shared/types'
import { OmniInputBox } from './OmniInputBox'
import { SuggestionChips } from './SuggestionChips'
import { EmergencyCall } from '../EmergencyCall'
import { MedicalNotice } from '../MedicalNotice'
import { snapState, tapHandle, type SheetState } from '../../lib/sheetState'

const SPRING = { type: 'spring' as const, stiffness: 300, damping: 28 }
const HANDLE_H = 44

interface BottomSheetProps {
  state: SheetState
  onStateChange: (state: SheetState) => void
  heights: Record<SheetState, number>
  bottomOffset: number
  messages: Message[]
  resultSlot: ReactNode
  /** Facilities tab content; shown instead of the thread while the sheet is in half. */
  listSlot: ReactNode
  showEmergencyStrip: boolean
  hasConversation: boolean
  onNewConversation: () => void
  omniValue: string
  onOmniChange: (v: string) => void
  onSend: () => void
  inputDisabled: boolean
  onChipSelect: (text: string) => void
  progressStage: 'idle' | 'typing' | 'analyzing' | 'complete'
  locationNotice: string | null
  busyText: string | null
  starterPrompts: string[]
}

function MessageBubble({ msg, isLastAssistant }: { msg: Message; isLastAssistant: boolean }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`} data-last-assistant={isLastAssistant ? '' : undefined}>
      <div
        className="max-w-[85%] px-3 py-2 text-[14px] leading-relaxed break-words"
        style={{
          background: isUser ? 'rgba(72,246,193,0.15)' : 'rgba(10,29,39,1)',
          border: isUser
            ? '1px solid rgba(72,246,193,0.20)'
            : '1px solid rgba(28,70,89,0.40)',
          borderRadius: isUser ? '10px 10px 2px 10px' : '10px 10px 10px 2px',
          color: '#E2F1F5',
        }}
      >
        {msg.content}
      </div>
    </div>
  )
}

const STATUS_TEXT = {
  idle: 'Ready to assist you',
  complete: 'Ready to assist you',
  typing: 'Sending...',
  analyzing: 'Analyzing symptoms...',
} as const

export function BottomSheet({
  state, onStateChange, heights, bottomOffset,
  messages, resultSlot, listSlot, showEmergencyStrip, hasConversation, onNewConversation,
  omniValue, onOmniChange, onSend, inputDisabled, onChipSelect,
  progressStage, locationNotice, busyText, starterPrompts,
}: BottomSheetProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const height = heights[state]

  // Newest message (or result) always in view.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (state === 'half') { el.scrollTop = 0; return }
    // With a result on screen, start at the reply (its 911 line and notice), not below it.
    const reply = resultSlot ? el.querySelector<HTMLElement>('[data-last-assistant]') : null
    if (reply) el.scrollTop = Math.max(0, reply.offsetTop - el.offsetTop - 8)
    else el.scrollTop = el.scrollHeight
  }, [messages.length, resultSlot, state, height])

  const lastAssistantId = [...messages].reverse().find(m => m.role === 'assistant')?.id

  const handlePanEnd = (_: unknown, info: PanInfo) => {
    // Dragging up (negative y) makes the sheet taller.
    onStateChange(snapState({ visible: height - info.offset.y, velocityY: info.velocity.y, current: state, heights }))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowUp' && state !== 'full') onStateChange(state === 'peek' ? 'half' : 'full')
    else if (e.key === 'ArrowDown' && state !== 'peek') onStateChange(state === 'full' ? 'half' : 'peek')
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onStateChange(tapHandle(state)) }
  }

  return (
    <motion.section
      aria-label="AI Health Assistant"
      initial={false}
      animate={{ height }}
      transition={SPRING}
      style={{
        position: 'fixed',
        bottom: bottomOffset,
        left: 0,
        right: 0,
        background: 'rgba(10,29,39,0.96)',
        backdropFilter: 'blur(16px)',
        borderTop: '1px solid rgba(28,70,89,0.50)',
        borderRadius: '24px 24px 0 0',
        zIndex: 20,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Handle strip: drag, tap or arrow keys. Also carries the medical notice so it shows in every state. */}
      <motion.div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize chat panel"
        aria-valuetext={state}
        tabIndex={0}
        onPanEnd={handlePanEnd}
        onTap={() => onStateChange(tapHandle(state))}
        onKeyDown={handleKeyDown}
        className="flex-none flex flex-col items-center justify-center select-none focus-visible:outline focus-visible:outline-2"
        style={{ height: HANDLE_H, touchAction: 'none', cursor: 'grab' }}
      >
        <div className="rounded-full" style={{ width: 36, height: 4, background: 'rgba(133,164,177,0.6)' }} />
        <MedicalNotice />
      </motion.div>

      {/* Thread area (clipped away in peek) */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-4 flex flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="font-semibold text-[15px]" style={{ color: '#E2F1F5' }}>AI Health Assistant</p>
            <p role="status" aria-live="polite" className="text-[12px]" style={{ color: '#85A4B1' }}>
              {STATUS_TEXT[progressStage]}
            </p>
          </div>
          {hasConversation && (
            <button
              type="button"
              onClick={onNewConversation}
              className="flex-none text-[13px] font-semibold rounded-lg px-3"
              style={{ minHeight: 44, border: '1px solid rgba(28,70,89,0.65)', background: 'transparent', color: '#48F6C1', cursor: 'pointer' }}
            >
              New conversation
            </button>
          )}
        </div>
        {!showEmergencyStrip && <EmergencyCall variant="link" />}
        {state === 'half' ? listSlot : (
          <>
            {messages.map(msg => <MessageBubble key={msg.id} msg={msg} isLastAssistant={msg.id === lastAssistantId} />)}
            {resultSlot}
            {messages.length === 0 && (
              <SuggestionChips chips={starterPrompts} onSelect={onChipSelect} disabled={inputDisabled} />
            )}
          </>
        )}
      </div>

      {/* Footer: pinned to the bottom of the sheet, above the keyboard */}
      <div className="flex-none px-4 pb-2 flex flex-col gap-2">
        {showEmergencyStrip && <EmergencyCall variant="primary" onOpen={() => onStateChange('full')} />}
        {busyText && (
          <div role="status" data-testid="busy-banner" className="text-[12px]" style={{ color: '#E2F1F5' }}>
            {busyText}
          </div>
        )}
        <OmniInputBox value={omniValue} onChange={onOmniChange} onSend={onSend} disabled={inputDisabled} />
        {locationNotice && (
          <p className="text-[12px] text-center" style={{ color: '#85A4B1' }}>{locationNotice}</p>
        )}
      </div>
    </motion.section>
  )
}
