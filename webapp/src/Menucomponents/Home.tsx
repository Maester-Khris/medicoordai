import { useState, useEffect } from 'react'
import type { Facility, Message, Session, ConversationsCache, ChatMessageResponse } from '@shared/types'
import { MapPanel } from '../components/map'
import { ChatPanel } from './subcomponent/ChatPanel'
import { LoginModal } from '../components/auth/LoginModal'
import { UserMenu } from '../components/auth/UserMenu'
import { WebNavBar } from '../components/WebNavBar'
import { useAuth } from '../auth/useAuth'
import { useProfile } from '../hooks/useProfile'
import { useGeolocation } from '../hooks/useGeolocation'
import { useTriageState } from '../hooks/useTriageState'

interface HomeProps {
  facilities: Facility[]
  facilitiesLoading: boolean
  conversationsCache: ConversationsCache | null
  sendMessage: (sessionId: string, content: string, coords?: { lat: number; lng: number } | null) => Promise<ChatMessageResponse | null>
  createSession: (firstMessage: string) => Promise<Session | null>
  loadOlderMessages: (sessionId: string, beforeId: string) => Promise<Message[]>
  busyUntil: number | null
}

const GLASS_PANEL: React.CSSProperties = {
  background: 'rgba(10, 29, 39, 0.82)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(28, 70, 89, 0.55)',
  boxShadow: '0 20px 40px -15px rgba(3, 10, 14, 0.7)',
  borderRadius: 12,
}

export default function Home({ facilities, facilitiesLoading, conversationsCache, sendMessage, createSession, loadOlderMessages, busyUntil }: HomeProps) {
  const { user, isGuest } = useAuth()
  const { profile } = useProfile()
  const geo = useGeolocation()
  const { triage, applyTriageResult, reset: triageReset } = useTriageState()
  const [sessionKey, setSessionKey] = useState(0)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [modalTab, setModalTab] = useState<"signin" | "signup">("signin")

  const handleNewConversation = () => {
    triageReset()
    setSessionKey(k => k + 1)
  }

  const openSignIn = () => { setModalTab("signin"); setIsModalOpen(true) }
  const openSignUp = () => { setModalTab("signup"); setIsModalOpen(true) }

  useEffect(() => {
    if (!user) geo.setCoords(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  return (
    <div className="flex flex-col h-screen" style={{ background: '#061219' }}>
      <LoginModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} defaultTab={modalTab} />

      <WebNavBar
        rightContent={isGuest ? null : user ? (
          <UserMenu />
        ) : (
          <>
            <button
              className="text-label-md font-medium transition-colors"
              style={{ color: '#7AA0B0', background: 'none', border: 'none', cursor: 'pointer' }}
              onMouseEnter={e => ((e.currentTarget as HTMLElement).style.color = '#E2F1F5')}
              onMouseLeave={e => ((e.currentTarget as HTMLElement).style.color = '#7AA0B0')}
              onClick={openSignIn}
            >
              Sign in
            </button>
            <button
              className="flex items-center gap-2 text-label-md font-semibold transition-all active:scale-95"
              style={{
                padding: '8px 18px',
                color: '#061219',
                background: '#48F6C1',
                border: 'none',
                borderRadius: 8,
                cursor: 'pointer',
              }}
              onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = '#3ce0ad')}
              onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = '#48F6C1')}
              onClick={openSignUp}
            >
              Get started
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path d="M5 12h14M12 5l7 7-7 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </>
        )}
      />

      {/* Body — sidebar left (40%) + map right (60%) */}
      <div className="flex flex-1 overflow-hidden" style={{ padding: '12px 16px 12px', gap: 12 }}>

        {/* Chat sidebar — LEFT, 25% */}
        <div className="flex-[1] overflow-hidden relative min-w-[260px]" style={GLASS_PANEL}>
          <ChatPanel
            key={sessionKey}
            user={user}
            cache={conversationsCache}
            sendMessage={sendMessage}
            createSession={createSession}
            loadOlderMessages={loadOlderMessages}
            geo={geo}
            profile={profile}
            triage={triage}
            onTriageResult={applyTriageResult}
            onNewConversation={handleNewConversation}
            busyUntil={busyUntil}
          />
        </div>

        {/* Map panel — RIGHT, 75% */}
        <div className="flex-[3] overflow-hidden relative" style={GLASS_PANEL}>
          <MapPanel
            facilities={facilities}
            facilitiesLoading={facilitiesLoading}
            triage={triage}
            onClear={handleNewConversation}
          />
        </div>
      </div>

      {/* Footer */}
      <div
        className="flex-none flex items-center justify-center px-8"
        style={{
          height: 28,
          fontSize: 11,
          borderTop: '0.5px solid rgba(28, 70, 89, 0.5)',
          color: '#7AA0B0',
        }}
      >
        <span style={{ fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}>
          MediCoord AI · Health Tech Platform
        </span>
      </div>
    </div>
  )
}
