// webapp/src/components/mobile/MobileLayout.tsx
import { useState, useCallback, useEffect } from 'react'
import { useConfig } from "../../hooks/useConfig"
import { FALLBACK_NOTICE, requestLocation, resolveDemoCoords } from "../../lib/demoLocation"
import type {
  Facility,
  Message,
  Session,
  ConversationsCache,
  TriageResult,
} from '@shared/types'
import { MapPanel } from '../map'
import { MobileTopBar } from './MobileTopBar'
import { DrawerMenu } from './DrawerMenu'
import { BottomNavBar, type MobileTab } from './BottomNavBar'
import { BottomSheet } from './BottomSheet'
import { FacilityCardPanel } from './FacilityCardPanel'
import { useAuth } from '../../auth/useAuth'
import { useSheetGeometry } from '../../hooks/useSheetGeometry'
import { stateForTab, tabForState, type SheetState } from '../../lib/sheetState'
import { useGeolocation } from '../../hooks/useGeolocation'
import { useTriageState } from '../../hooks/useTriageState'
import { useNextActions } from '../../hooks/useNextActions'
import type { SendResult } from '../../hooks/useConversations'
import { failureMessage } from '../../lib/sendFailure'
import { busyMessage } from '../../lib/busy'

interface MobileLayoutProps {
  facilities: Facility[]
  facilitiesLoading: boolean
  conversationsCache: ConversationsCache | null
  sendMessage: (
    sessionId: string,
    content: string,
    coords?: { lat: number; lng: number } | null
  ) => Promise<SendResult>
  createSession: (firstMessage: string) => Promise<Session | null>
  loadOlderMessages: (sessionId: string, beforeId: string) => Promise<Message[]>
  busyUntil: number | null
}

type ProgressStage = 'idle' | 'typing' | 'analyzing' | 'complete'

function stripToolNarration(content: string): string {
  return content
    .replace(/I'm going to call[\s\S]*?triage_response\([^)]*\)\s*/gi, '')
    .trim()
}

const FALLBACK_STARTERS = ['I have a fever', 'Chest pain', 'Sore throat', 'Dizziness']

export function MobileLayout({
  facilities,
  facilitiesLoading,
  sendMessage,
  createSession,
  busyUntil,
}: MobileLayoutProps) {
  const { user, isGuest } = useAuth()
  const config = useConfig()
  const [usingFallbackLocation, setUsingFallbackLocation] = useState(false)
  const geo = useGeolocation()
  const { triage, applyTriageResult, changeMode, reset: triageReset } = useTriageState()
  const { getDirections } = useNextActions()

  // Chat state (previously in AiAssistantTab)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [omniValue, setOmniValue] = useState('')
  const [progressStage, setProgressStage] = useState<ProgressStage>('idle')

  // Nav
  const [sheetState, setSheetState] = useState<SheetState>('peek')
  const geometry = useSheetGeometry()
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)

  // Mode derived from triage state
  const mode = triage.active ? 'recommendation' : 'browse'
  const isBusy = busyUntil !== null
  // While the keyboard is up the sheet is full, so the thread and the input stay above it.
  const effectiveState: SheetState = geometry.keyboardOpen ? 'full' : sheetState
  const emergentResult = triage.active && triage.severity === 'emergent'
  const heights: Record<SheetState, number> = {
    peek: Math.min(geometry.peek + (emergentResult ? 56 : 0), geometry.half - 1), // + the Call 911 strip
    half: geometry.half,
    full: geometry.full,
  }

  // Reset on user logout
  useEffect(() => {
    if (!user) geo.setCoords(null)
  }, [user]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleNewConversation = useCallback(() => {
    triageReset()
    setActiveSessionId(null)
    setMessages([])
    setOmniValue('')
    setProgressStage('idle')
  }, [triageReset])

  const handleApplyTriage = useCallback(async (
    result: TriageResult,
    coords: { lat: number; lng: number } | null,
    sessionId: string,
  ) => {
    await applyTriageResult(result, coords, sessionId)
  }, [applyTriageResult])

  const handleSend = useCallback(async (starter?: string) => {
    const text = (starter ?? omniValue).trim()
    if (!text || !user || busyUntil !== null) return
    setOmniValue('')
    setSheetState('full')

    let coords = geo.coords
    if (!coords) coords = await requestLocation(geo.requestOnce, config)

    const located = resolveDemoCoords(coords, config)
    coords = located.coords
    setUsingFallbackLocation(located.usedFallback)

    let sid = activeSessionId
    if (!sid) {
      const session = await createSession(text)
      if (!session) {
        setOmniValue(text)
        setMessages(prev => [...prev, failureMessage('', user.id)])
        return
      }
      sid = session.id
      setActiveSessionId(sid)
    }

    const optimisticMsg: Message = {
      id: crypto.randomUUID(),
      session_id: sid,
      user_id: user.id,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, optimisticMsg])
    setProgressStage('typing')

    const response = await sendMessage(sid, text, coords)
    if (response === 'busy' || response === 'failed') {
      // Keep the text for a retry; the busy banner already explains a busy answer.
      setMessages(prev => {
        const kept = prev.filter(m => m.id !== optimisticMsg.id)
        return response === 'failed' ? [...kept, failureMessage(sid, user.id)] : kept
      })
      setOmniValue(text)
      setProgressStage('idle')
    } else {
      const cleaned = {
        ...response.assistant_message,
        content: stripToolNarration(response.assistant_message.content),
      }
      setMessages(prev => [
        ...prev.filter(m => m.id !== optimisticMsg.id),
        optimisticMsg,
        cleaned,
      ])
      if (response.triage) {
        setProgressStage('analyzing')
        await handleApplyTriage(response.triage, coords, sid)
        setProgressStage('complete')
        setTimeout(() => setProgressStage('idle'), 800)
      } else {
        setProgressStage('idle')
      }
    }
  }, [omniValue, user, geo, activeSessionId, createSession, sendMessage, handleApplyTriage, config, busyUntil])

  const handleTabChange = useCallback((tab: MobileTab) => setSheetState(stateForTab(tab)), [])

  const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
  const feedback = isGuest && activeSessionId && lastAssistant
    ? { sessionId: activeSessionId, messageId: lastAssistant.id }
    : null

  return (
    // Full-viewport shell — map underneath everything
    <div
      className="relative overflow-hidden"
      style={{ width: '100vw', height: '100dvh' }}
    >
      {/* Map canvas — always mounted, fills space between top bar and bottom nav */}
      <div
        style={{
          position: 'fixed',
          top: 56,    // MobileTopBar height
          bottom: 64, // BottomNavBar height
          left: 0,
          right: 0,
          zIndex: 0,
        }}
      >
        <MapPanel
          facilities={facilities}
          facilitiesLoading={facilitiesLoading}
          triage={triage}
          verticalLegend
          sizeVersion={0}
          onClear={handleNewConversation}
          onModeChange={mode => { void changeMode(mode) }}
        />
      </div>

      {/* Fixed top bar */}
      <MobileTopBar
        mode={mode}
        severity={triage.severity}
        onMenuOpen={isGuest ? undefined : () => setIsDrawerOpen(true)}
      />

      <BottomSheet
        state={effectiveState}
        onStateChange={setSheetState}
        heights={heights}
        bottomOffset={geometry.bottomOffset}
        messages={messages}
        resultSlot={triage.active ? (
          <FacilityCardPanel
            feedback={feedback}
            triage={triage}
            onModeChange={mode => { void changeMode(mode) }}
            onGetDirections={(name, lat, lng) => getDirections(name, lat, lng)}
          />
        ) : null}
        showEmergencyStrip={triage.active && triage.severity === 'emergent'}
        hasConversation={messages.length > 0 || triage.active}
        onNewConversation={handleNewConversation}
        omniValue={omniValue}
        onOmniChange={setOmniValue}
        onSend={() => { void handleSend() }}
        inputDisabled={!user || isBusy}
        onChipSelect={v => { void handleSend(v) }}
        progressStage={progressStage}
        locationNotice={usingFallbackLocation ? FALLBACK_NOTICE : null}
        starterPrompts={config.starter_prompts.length > 0 ? config.starter_prompts : FALLBACK_STARTERS}
        busyText={isBusy ? busyMessage(busyUntil, Date.now()) : null}
      />

      {/* Fixed bottom nav */}
      <BottomNavBar activeTab={tabForState(effectiveState)} onTabChange={handleTabChange} />

      {/* Drawer menu */}
      {!isGuest && <DrawerMenu isOpen={isDrawerOpen} onClose={() => setIsDrawerOpen(false)} />}
    </div>
  )
}
