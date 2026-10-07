import { useState, useRef, useEffect, useCallback } from "react"
import type { Message, Session, ConversationsCache, ChatMessageResponse, TriageResult, TriageUIState } from "@shared/types"
import { TriageCard } from "../../components/triage/TriageCard"
import { ToolCallProgress } from "../../components/triage/ToolCallProgress"
import type { GeolocationPermission } from "../../hooks/useGeolocation"
import { useConfig } from "../../hooks/useConfig"
import { FALLBACK_NOTICE, resolveDemoCoords } from "../../lib/demoLocation"

interface AuthUser {
  id: string
  email: string | undefined
}

interface GeoProps {
  coords: { lat: number; lng: number } | null
  requestOnce: () => Promise<{ lat: number; lng: number } | null>
  permission: GeolocationPermission
}

interface ProfileProps {
  location_preference: 'always' | 'ask'
  emergency_contact_phone?: string | null
}

type ProgressStage = "idle" | "typing" | "analyzing" | "locating" | "complete"

interface ChatPanelProps {
  user: AuthUser | null
  cache: ConversationsCache | null
  sendMessage: (sessionId: string, content: string, coords?: { lat: number; lng: number } | null) => Promise<ChatMessageResponse | null>
  createSession: (firstMessage: string) => Promise<Session | null>
  loadOlderMessages: (sessionId: string, beforeId: string) => Promise<Message[]>
  geo: GeoProps
  profile: ProfileProps | null
  triage: TriageUIState
  onTriageResult: (result: TriageResult, coords: { lat: number; lng: number } | null) => Promise<void>
  onNewConversation: () => void
}

const SUGGESTIONS = [
  "I have a fever and sore throat",
  "Chest pain and shortness of breath",
  "Twisted my ankle — it's swollen",
]

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString("en-CA", { month: "short", day: "numeric" })
}

function stripToolNarration(content: string): string {
  return content
    .replace(/I'm going to call[\s\S]*?triage_response\([^)]*\)\s*/gi, "")
    .trim()
}

export function ChatPanel({
  user,
  cache,
  sendMessage,
  createSession,
  loadOlderMessages,
  geo,
  profile,
  triage,
  onTriageResult,
  onNewConversation,
}: ChatPanelProps) {
  const config = useConfig()
  const [usingFallbackLocation, setUsingFallbackLocation] = useState(false)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [content, setContent] = useState("")
  const [pastConversationsOpen, setPastConversationsOpen] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [progressStage, setProgressStage] = useState<ProgressStage>("idle")
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = "auto"
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`
    }
  }, [content])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [localMessages])

  const handleNewConversation = () => {
    setActiveSessionId(null)
    setLocalMessages([])
    setContent("")
    setPastConversationsOpen(false)
    onNewConversation()
  }

  const handleSelectSession = (session: Session) => {
    setActiveSessionId(session.id)
    setLocalMessages(cache?.messages[session.id] ?? [])
    setPastConversationsOpen(false)
  }

  const handleSend = async () => {
    if (!content.trim() || !user) return
    const text = content.trim()
    setContent("")

    let coords = geo.coords
    if (!coords) {
      if (profile?.location_preference === 'always') {
        coords = await geo.requestOnce()
      } else if (!activeSessionId) {
        coords = await geo.requestOnce()
      }
    }

    const located = resolveDemoCoords(coords, config)
    coords = located.coords
    setUsingFallbackLocation(located.usedFallback)

    let sid = activeSessionId
    if (!sid) {
      const session = await createSession(text)
      if (!session) return
      sid = session.id
      setActiveSessionId(sid)
    }

    const optimisticUserMsg: Message = {
      id: crypto.randomUUID(),
      session_id: sid,
      user_id: user.id,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    }
    setLocalMessages(prev => [...prev, optimisticUserMsg])

    setProgressStage("typing")
    const response = await sendMessage(sid, text, coords)

    if (response) {
      const cleanedAssistant = {
        ...response.assistant_message,
        content: stripToolNarration(response.assistant_message.content),
      }
      setLocalMessages(prev => [
        ...prev.filter(m => m.id !== optimisticUserMsg.id),
        optimisticUserMsg,
        cleanedAssistant,
      ])
      if (response.triage) {
        setProgressStage("analyzing")
        await onTriageResult(response.triage, coords)
        setProgressStage("complete")
        setTimeout(() => setProgressStage("idle"), 800)
      } else {
        setProgressStage("idle")
      }
    } else {
      setProgressStage("idle")
    }
  }

  const handleScroll = useCallback(async () => {
    const el = scrollContainerRef.current
    if (!el || !activeSessionId || localMessages.length === 0) return
    if (el.scrollTop > 50) return
    if (loadMoreRef.current) return

    const oldest = localMessages[0]
    if (!oldest.created_at.includes("+")) return

    loadMoreRef.current = true
    setLoadingOlder(true)
    try {
      const older = await loadOlderMessages(activeSessionId, oldest.id)
      if (older.length > 0) setLocalMessages(prev => [...older, ...prev])
    } finally {
      setLoadingOlder(false)
      loadMoreRef.current = false
    }
  }, [activeSessionId, localMessages, loadOlderMessages])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const sessions = cache?.sessions ?? []
  const hasMessages = localMessages.length > 0
  const lastMsg = localMessages[localMessages.length - 1]
  const showTriageCard = triage.active && lastMsg?.role === "assistant"

  return (
    <div className="flex flex-col h-full relative" style={{ background: 'transparent' }}>

      {/* Panel header */}
      <div
        className="flex-none px-5 py-3.5 z-20 relative"
        style={{ borderBottom: '1px solid rgba(28, 70, 89, 0.6)' }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center flex-none"
              style={{ background: 'rgba(72, 246, 193, 0.12)', border: '1px solid rgba(72, 246, 193, 0.25)' }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M12 4V20M4 12H20" stroke="#48F6C1" strokeWidth="2.5" strokeLinecap="round" />
                <circle cx="12" cy="12" r="8" stroke="#48F6C1" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="4 4" />
              </svg>
            </div>
            <div>
              <h2 className="text-[14px] font-bold tracking-tight leading-tight" style={{ color: '#E2F1F5' }}>
                AI Health Assistant
              </h2>
              <p className="text-[11px] font-semibold mt-0.5" style={{ color: '#48F6C1' }}>
                Ready to assist you
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleNewConversation}
              disabled={!user}
              className="flex items-center gap-1.5 text-xs font-semibold rounded-lg transition-all"
              style={{
                padding: '5px 10px',
                color: user ? '#7AA0B0' : '#1C4659',
                border: `0.5px solid ${user ? 'rgba(28,70,89,0.6)' : 'rgba(28,70,89,0.3)'}`,
                background: 'rgba(6,18,25,0.4)',
                cursor: user ? 'pointer' : 'not-allowed',
              }}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
              </svg>
              New conversation
            </button>
            <div
              className="flex items-center gap-1.5 rounded-full"
              style={{
                padding: '4px 10px',
                background: 'rgba(72, 246, 193, 0.08)',
                border: '1px solid rgba(72, 246, 193, 0.2)',
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: '#48F6C1' }} />
              <span className="text-[10px] font-bold uppercase tracking-wide" style={{ color: '#48F6C1' }}>Online</span>
            </div>
          </div>
        </div>
      </div>

      {/* Past conversations */}
      {user && sessions.length > 0 && (
        <div className="flex-none z-10" style={{ borderBottom: '1px solid rgba(28, 70, 89, 0.4)' }}>
          <button
            onClick={() => setPastConversationsOpen(o => !o)}
            className="w-full flex items-center justify-between transition-colors"
            style={{
              padding: '8px 20px',
              fontSize: 12,
              fontWeight: 600,
              color: '#7AA0B0',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            <span>Past conversations</span>
            <svg
              width="13" height="13" viewBox="0 0 24 24" fill="none"
              className={`transition-transform ${pastConversationsOpen ? "rotate-180" : ""}`}
            >
              <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {pastConversationsOpen && (
            <div style={{ borderTop: '1px solid rgba(28, 70, 89, 0.3)' }}>
              {sessions.map(session => (
                <button
                  key={session.id}
                  onClick={() => handleSelectSession(session)}
                  className="w-full flex items-center justify-between text-left transition-colors"
                  style={{
                    padding: '8px 20px',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: '#E2F1F5',
                  }}
                  onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = 'rgba(28,70,89,0.25)')}
                  onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = 'none')}
                >
                  <span className="text-sm truncate" style={{ color: '#E2F1F5' }}>{session.title}</span>
                  <span className="text-xs flex-none ml-2" style={{ color: '#7AA0B0' }}>{formatDate(session.updated_at)}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Message area / empty state */}
      {hasMessages ? (
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto px-4 py-4"
        >
          <div className="flex flex-col justify-end min-h-full gap-3">
            {loadingOlder && (
              <div className="text-center text-xs py-2" style={{ color: '#7AA0B0' }}>
                Loading older messages…
              </div>
            )}
            {localMessages.map((msg, idx) => {
              const isLastAssistant = msg.role === "assistant" && idx === localMessages.length - 1
              return (
                <div key={msg.id}>
                  <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div
                      className="max-w-[80%] min-w-0 rounded-2xl px-4 py-2.5 text-sm break-words overflow-hidden"
                      style={msg.role === "user"
                        ? {
                            background: '#48F6C1',
                            color: '#061219',
                            borderBottomRightRadius: 4,
                            fontWeight: 500,
                          }
                        : {
                            background: 'rgba(19, 46, 60, 0.9)',
                            border: '1px solid rgba(28, 70, 89, 0.5)',
                            color: '#E2F1F5',
                            borderBottomLeftRadius: 4,
                          }
                      }
                    >
                      {msg.content}
                    </div>
                  </div>
                  {isLastAssistant && showTriageCard && (
                    <div className="mt-1 max-w-[80%]">
                      <TriageCard
                        triage={triage}
                        emergencyContactPhone={profile?.emergency_contact_phone ?? null}
                      />
                    </div>
                  )}
                </div>
              )
            })}
            <div ref={messagesEndRef} />
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center px-6 gap-5 overflow-hidden relative">
          {/* Subtle grid pattern */}
          <div
            className="absolute inset-0 opacity-[0.04]"
            style={{
              backgroundImage: 'linear-gradient(rgba(72,246,193,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(72,246,193,0.5) 1px, transparent 1px)',
              backgroundSize: '32px 32px',
            }}
          />
          <div className="text-center z-10 flex flex-col items-center">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
              style={{
                background: 'rgba(72, 246, 193, 0.1)',
                border: '1px solid rgba(72, 246, 193, 0.25)',
                boxShadow: '0 0 24px rgba(72,246,193,0.1)',
              }}
            >
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
                <path d="M8 10h8M8 14h4M21 12c0 4.97-4.03 9-9 9-2.07 0-3.98-.7-5.5-1.88L3 20l.88-3.5C2.7 14.98 2 13.07 2 12c0-4.97 4.03-9 9-9s9 4.03 9 9z" stroke="#48F6C1" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h3 className="text-lg font-bold tracking-tight" style={{ color: '#E2F1F5' }}>
              How are you feeling?
            </h3>
            <p className="text-sm font-medium mt-1.5 max-w-[220px]" style={{ color: '#7AA0B0' }}>
              Describe your symptoms or ask a health-related question.
            </p>
          </div>
          <div className="flex flex-col gap-2.5 w-full z-10">
            {SUGGESTIONS.map(s => (
              <button
                key={s}
                onClick={() => { if (user) setContent(s) }}
                className="w-full flex items-center gap-3 text-left text-sm font-medium transition-all rounded-xl"
                style={{
                  padding: '10px 14px',
                  color: '#E2F1F5',
                  background: 'rgba(10, 29, 39, 0.6)',
                  border: '1px solid rgba(28, 70, 89, 0.5)',
                  cursor: user ? 'pointer' : 'default',
                }}
                onMouseEnter={e => {
                  if (!user) return
                  ;(e.currentTarget as HTMLElement).style.borderColor = 'rgba(72,246,193,0.4)'
                  ;(e.currentTarget as HTMLElement).style.background = 'rgba(72,246,193,0.06)'
                }}
                onMouseLeave={e => {
                  ;(e.currentTarget as HTMLElement).style.borderColor = 'rgba(28, 70, 89, 0.5)'
                  ;(e.currentTarget as HTMLElement).style.background = 'rgba(10, 29, 39, 0.6)'
                }}
              >
                <div
                  className="w-6 h-6 rounded-full flex items-center justify-center flex-none"
                  style={{ background: 'rgba(28, 70, 89, 0.5)' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                    <path d="M5 12h14M12 5l7 7-7 7" stroke="#7AA0B0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <span className="truncate">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Progress trace */}
      <ToolCallProgress stage={progressStage} />

      {/* Input area */}
      <div
        className="flex-none px-4 py-3 z-20 relative"
        style={{ borderTop: '1px solid rgba(28, 70, 89, 0.5)' }}
      >
        {/* Omni-input box per design spec */}
        <div
          className="relative flex items-center transition-all"
          style={{
            background: 'rgba(19, 46, 60, 0.7)',
            border: '1px solid rgba(28, 70, 89, 0.65)',
            borderRadius: 10,
            padding: '2px 4px 2px 2px',
          }}
          onFocusCapture={e => {
            const el = e.currentTarget as HTMLElement
            el.style.border = '1px solid rgba(72, 246, 193, 0.6)'
            el.style.boxShadow = '0 0 0 3px rgba(72,246,193,0.08)'
          }}
          onBlurCapture={e => {
            const el = e.currentTarget as HTMLElement
            el.style.border = '1px solid rgba(28, 70, 89, 0.65)'
            el.style.boxShadow = 'none'
          }}
        >
          <div className="pl-3 pr-1" style={{ color: '#48F6C1', opacity: 0.7 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M9 21h6m-3-18c-3.866 0-7 3.134-7 7 0 2.21 1.028 4.185 2.632 5.487C9.28 16.035 9.8 16.924 9.8 17.9V19a2 2 0 002 2h4a2 2 0 002-2v-1.1c0-.976.52-1.865 1.168-2.413C20.972 14.185 22 12.21 22 10c0-3.866-3.134-7-7-7z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <textarea
            ref={textareaRef}
            disabled={!user}
            value={content}
            onChange={e => setContent(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex-1 resize-none text-[13px] font-medium px-2 py-2.5 focus:outline-none"
            style={{
              background: 'transparent',
              color: '#E2F1F5',
              caretColor: '#48F6C1',
              cursor: user ? 'text' : 'not-allowed',
              maxHeight: '120px',
              height: 'auto',
              overflowY: 'auto',
            }}
            placeholder={user ? "Describe how you feel…" : "Sign in to start a conversation"}
            rows={1}
          />
          {/* Ctrl+K badge */}
          <span
            className="flex-none mr-1.5 hidden sm:flex items-center rounded text-mono-meta"
            style={{
              padding: '2px 5px',
              border: '1px solid rgba(28,70,89,0.6)',
              background: 'rgba(10,29,39,0.4)',
              color: '#7AA0B0',
              fontSize: 10,
              letterSpacing: '0.04em',
              userSelect: 'none',
            }}
          >
            ⌘K
          </span>
          <div className="pr-1 pl-1">
            <button
              disabled={!user || !content.trim()}
              onClick={handleSend}
              className="w-8 h-8 rounded-lg flex items-center justify-center transition-all active:scale-95"
              style={{
                color: '#061219',
                background: user && content.trim() ? '#48F6C1' : 'rgba(28, 70, 89, 0.4)',
                border: 'none',
                cursor: user && content.trim() ? 'pointer' : 'not-allowed',
              }}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke={user && content.trim() ? '#061219' : '#7AA0B0'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>

        {usingFallbackLocation ? (
          <p className="text-[10px] font-semibold text-center mt-2" style={{ color: '#7AA0B0' }}>
            {FALLBACK_NOTICE}
          </p>
        ) : geo.permission === "denied" ? (
          <p className="text-[10px] font-semibold text-center mt-2" style={{ color: '#F59E0B' }}>
            ⚠ Location blocked — facility map routing unavailable
          </p>
        ) : (
          <p className="text-[10px] font-semibold text-center mt-2 flex items-center justify-center gap-1.5" style={{ color: '#7AA0B0', fontFamily: 'var(--font-mono)' }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Secure &amp; confidential · Location synced
          </p>
        )}
      </div>
    </div>
  )
}
