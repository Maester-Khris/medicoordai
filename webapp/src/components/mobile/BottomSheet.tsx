// webapp/src/components/mobile/BottomSheet.tsx
import { useRef, useCallback, useState } from 'react'
import { motion, useMotionValue, animate, type PanInfo } from 'motion/react'
import type { Message } from '@shared/types'
import { OmniInputBox } from './OmniInputBox'
import { SuggestionChips } from './SuggestionChips'

const COLLAPSED_H = 220
const BOTTOM_NAV_H = 64
const SPRING = { type: 'spring' as const, stiffness: 300, damping: 28 }

interface BottomSheetProps {
  messages: Message[]
  omniValue: string
  onOmniChange: (v: string) => void
  onSend: () => void
  inputDisabled: boolean
  onChipSelect: (text: string) => void
  progressStage: 'idle' | 'typing' | 'analyzing' | 'complete'
  locationNotice: string | null
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className="max-w-[80%] px-3 py-2 text-[14px] leading-relaxed break-words"
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

export function BottomSheet({
  messages,
  omniValue,
  onOmniChange,
  onSend,
  inputDisabled,
  onChipSelect,
  progressStage,
  locationNotice,
}: BottomSheetProps) {
  const expandedH = Math.round(window.innerHeight * 0.85)
  const slideOffset = expandedH - COLLAPSED_H // y when collapsed

  const y = useMotionValue(slideOffset)
  const [isExpanded, setIsExpanded] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const snapTo = useCallback(
    (expanded: boolean) => {
      setIsExpanded(expanded)
      animate(y, expanded ? 0 : slideOffset, SPRING)
    },
    [y, slideOffset]
  )

  const handleDragEnd = useCallback(
    (_: unknown, info: PanInfo) => {
      const threshold = slideOffset * 0.35
      if (info.offset.y < -threshold || info.velocity.y < -300) {
        snapTo(true)
      } else if (info.offset.y > threshold || info.velocity.y > 300) {
        snapTo(false)
      } else {
        snapTo(isExpanded)
      }
    },
    [isExpanded, slideOffset, snapTo]
  )

  return (
    <motion.div
      drag="y"
      dragConstraints={{ top: 0, bottom: slideOffset }}
      dragElastic={0.05}
      onDragEnd={handleDragEnd}
      style={{
        y,
        position: 'fixed',
        bottom: BOTTOM_NAV_H,
        left: 0,
        right: 0,
        height: expandedH,
        background: 'rgba(10,29,39,0.92)',
        backdropFilter: 'blur(16px)',
        borderTop: '1px solid rgba(28,70,89,0.50)',
        borderRadius: '24px 24px 0 0',
        zIndex: 20,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Drag handle */}
      <div
        className="flex-none flex items-center justify-center pt-3 pb-2 select-none"
        style={{ touchAction: 'none', cursor: 'grab' }}
      >
        <div
          className="rounded-full"
          style={{ width: 36, height: 4, background: 'rgba(28,70,89,1)' }}
        />
      </div>

      {/* Header */}
      <div className="flex-none flex items-center justify-between px-4 mb-1">
        <span
          className="font-semibold text-[15px]"
          style={{ color: '#E2F1F5', fontFamily: 'var(--font-sans)' }}
        >
          AI Health Assistant
        </span>
        <span
          className="text-[18px] animate-pulse"
          style={{ color: '#48F6C1' }}
          aria-hidden="true"
        >
          ●
        </span>
      </div>

      {/* Subtitle */}
      <div className="flex-none px-4 mb-3">
        <span
          className="font-mono text-[10px] tracking-widest"
          style={{ color: '#85A4B1' }}
        >
          {progressStage === 'idle' || progressStage === 'complete'
            ? 'READY TO ASSIST YOU'
            : progressStage === 'typing'
            ? 'SENDING...'
            : 'ANALYZING SYMPTOMS...'}
        </span>
      </div>

      {/* Message thread (expanded only) */}
      {isExpanded && messages.length > 0 && (
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-4 pb-3 flex flex-col gap-3 min-h-0"
        >
          {messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
        </div>
      )}


      {/* Suggestion chips */}
      <div className="flex-none px-4 mb-3">
        <SuggestionChips onSelect={onChipSelect} disabled={inputDisabled} />
      </div>

      {/* Omni input */}
      <div className="flex-none px-4 mb-2">
        <OmniInputBox
          value={omniValue}
          onChange={onOmniChange}
          onSend={onSend}
          disabled={inputDisabled}
        />
      </div>

      {/* Security badge */}
      <div className="flex-none px-4 pb-3 text-center">
        <span
          className="font-mono text-[9px]"
          style={{ color: 'rgba(133,164,177,0.60)' }}
        >
          {locationNotice ?? <>🔒 SECURE &amp; CONFIDENTIAL · LOCATION SYNCED</>}
        </span>
      </div>
    </motion.div>
  )
}
