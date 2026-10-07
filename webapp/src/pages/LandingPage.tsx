import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'motion/react'
import { LoginModal } from '../components/auth/LoginModal'
import { useAuth } from '../auth/useAuth'
import { useDocumentHead } from '../hooks/useDocumentHead'
import { loadAnalytics } from '../lib/analytics'
import {
  MagnifyingGlass,
  Command,
  CircleNotch,
  Sparkle,
  ArrowRight,
  MapPin,
  ShieldCheck,
  Check,
  Info,
  Car,
  Bicycle,
  User,
  CaretDown,
  CaretUp,
  Stethoscope,
  TrafficSign
} from '@phosphor-icons/react'

const PLACEHOLDERS = [
  "Pediatrician open past 7pm nearby",
  "Urgent care clinic for deep cut",
  "Nearest ER with low wait time",
  "Diagnostic lab with rapid PCR testing"
]

const SAMPLE_CHIPS = [
  { text: "Pediatrician open past 7pm", query: "Pediatrician open past 7pm nearby" },
  { text: "Urgent care for cut", query: "Urgent care clinic for deep cut" },
  { text: "Nearest ER", query: "Nearest ER with low wait time" }
]

// Shared by the "How it works" section and its HowTo schema below — one source of truth.
const HOW_IT_WORKS_STEPS = [
  {
    id: 1,
    title: "1. You describe it",
    tagline: "Plain words, no medical jargon",
    desc: "Describe your situation in plain language. The AI asks follow-up questions to understand your symptoms fully.",
    icon: Sparkle
  },
  {
    id: 2,
    title: "2. We assess it",
    tagline: "Clinical context, understood",
    desc: "Your description is mapped to clinical severity and the right type of care — without replacing a doctor's judgment.",
    icon: Stethoscope
  },
  {
    id: 3,
    title: "3. We route you there",
    tagline: "Nearest care, fastest total time",
    desc: "Travel time plus live wait queue — so you arrive at the facility where you'll be seen soonest.",
    icon: TrafficSign
  }
] as const

const FAQ_ITEMS = [
  {
    q: "Is MediCoord AI a diagnosis tool?",
    a: "No. MediCoord AI classifies the urgency of your symptoms and routes you to the right type of facility — it does not diagnose conditions and is not a substitute for professional medical advice. For life-threatening emergencies, call emergency services directly."
  },
  {
    q: "Where does MediCoord AI work?",
    a: "MediCoord AI currently covers Toronto, Ontario, routing patients across the city's hospitals, urgent care clinics, and walk-in facilities using real Canadian public health data."
  },
  {
    q: "Is my symptom description stored?",
    a: "No. Your description is used only for the current session's routing decision — it is never stored beyond your session or used to train any AI model."
  },
  {
    q: "How does MediCoord AI pick a facility?",
    a: "It combines your classified severity with live facility wait queues and real-time driving/transit time, so you're routed to wherever you'll actually be seen soonest — not just the geographically nearest option."
  },
  {
    q: "Do I need an account to use it?",
    a: "No appointment, referral, or account is required to describe your symptoms and get routed to a facility."
  }
] as const

// Facility Coordinates (matching the generated base_map_canvas.png landmarks)
const HOSPITAL_PIN = { left: '28%', top: '50%' }
const CLINIC_PIN = { left: '58%', top: '51%' }
const LAB_PIN = { left: '81%', top: '54%' }

// Path coordinates for travelers (as percentages)
const CAR_PATH = [
  { left: '10', top: '92' },
  { left: '22', top: '78' },
  { left: '28', top: '70' },
  { left: '28', top: '50' }
]

const BIKE_PATH = [
  { left: '48', top: '92' },
  { left: '48', top: '72' },
  { left: '58', top: '60' },
  { left: '58', top: '51' }
]

const JOGGER_PATH = [
  { left: '92', top: '90' },
  { left: '81', top: '79' },
  { left: '81', top: '54' }
]

const FAMILY_PATH = [
  { left: '64', top: '22' },
  { left: '64', top: '40' },
  { left: '58', top: '46' },
  { left: '58', top: '51' }
]

type CookieSettings = { zoom: boolean; history: boolean; analytics: boolean }
const COOKIE_CONSENT_KEY = 'medicoord_cookie_consent'

function loadStoredConsent(): CookieSettings | null {
  try {
    const raw = localStorage.getItem(COOKIE_CONSENT_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function persistConsent(settings: CookieSettings) {
  try {
    localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify(settings))
  } catch {
    // localStorage unavailable (private browsing, etc.) — consent just won't persist across reloads
  }
}

// Path interpolation function
function interpolatePath(path: { left: string; top: string }[], progress: number) {
  if (progress <= 0) return path[0]
  if (progress >= 1) return path[path.length - 1]
  
  const totalSegments = path.length - 1
  const segment = Math.floor(progress * totalSegments)
  const segmentProgress = (progress * totalSegments) - segment
  
  const start = path[segment]
  const end = path[segment + 1]
  
  const startLeft = parseFloat(start.left)
  const endLeft = parseFloat(end.left)
  const startTop = parseFloat(start.top)
  const endTop = parseFloat(end.top)
  
  const currentLeft = startLeft + (endLeft - startLeft) * segmentProgress
  const currentTop = startTop + (endTop - startTop) * segmentProgress
  
  return {
    left: `${currentLeft}%`,
    top: `${currentTop}%`
  }
}

export default function LandingPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [modalTab, setModalTab] = useState<'signin' | 'signup'>('signin')

  // Search/Intent simulation states
  const [searchQuery, setSearchQuery] = useState('')
  const [placeholderIndex, setPlaceholderIndex] = useState(0)
  const [isCommandMenuOpen, setIsCommandMenuOpen] = useState(false)
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0)
  
  const [isTyping, setIsTyping] = useState(false)
  const [isParsing, setIsParsing] = useState(false)
  const [parsedIntents, setParsedIntents] = useState<string[]>([])
  const [parseComplete, setParseComplete] = useState(false)

  // Cookie Controller states — synchronous lazy initializer (matches
  // cookieSettings below) so the decision is made in the first render pass,
  // not a post-mount effect: keeps prerendered HTML and hydration in sync.
  const [cookieBannerOpen, setCookieBannerOpen] = useState(() => !loadStoredConsent())
  const [showPreferences, setShowPreferences] = useState(false)
  const [cookieSettings, setCookieSettings] = useState<CookieSettings>(
    () => loadStoredConsent() ?? { zoom: true, history: true, analytics: false }
  )
  const [activeStep, setActiveStep] = useState(1)

  useDocumentHead(
    'Find Urgent Care & ERs Near You — MediCoord AI Toronto',
    "Describe your symptoms and MediCoord AI finds the nearest clinic, urgent care, or ER in Toronto with real wait times. Know where to go before you go."
  )

  useEffect(() => {
    if (cookieSettings.analytics) loadAnalytics()
  }, [cookieSettings.analytics])

  // Animation timeline state (0 to 12 seconds)
  const [time, setTime] = useState(0)
  const typingTimerRef = useRef<NodeJS.Timeout | null>(null)

  // CENTRAL TIMELINE FOR HERO MAP LOOP (0s - 12s)
  useEffect(() => {
    const interval = setInterval(() => {
      setTime((prev) => (prev + 0.05) % 12)
    }, 50)
    return () => clearInterval(interval)
  }, [])

  // Cycling placeholder text when not typing or searching
  useEffect(() => {
    if (searchQuery || isTyping || isParsing) return
    const interval = setInterval(() => {
      setPlaceholderIndex((prev) => (prev + 1) % PLACEHOLDERS.length)
    }, 3500)
    return () => clearInterval(interval)
  }, [searchQuery, isTyping, isParsing])

  // Key listeners for command menu (Ctrl+K / Cmd+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setIsCommandMenuOpen((prev) => !prev)
      } else if (e.key === 'Escape') {
        setIsCommandMenuOpen(false)
      } else if (isCommandMenuOpen) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedCommandIndex((prev) => (prev + 1) % 4)
        } else if (e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedCommandIndex((prev) => (prev - 1 + 4) % 4)
        } else if (e.key === 'Enter') {
          e.preventDefault()
          handleSelectCommand(selectedCommandIndex)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isCommandMenuOpen, selectedCommandIndex])

  const openSignIn = () => { setModalTab('signin'); setIsModalOpen(true) }
  const openSignUp = () => { setModalTab('signup'); setIsModalOpen(true) }

  // Search Demo typing simulator
  const runSearchDemo = (targetQuery: string) => {
    setIsCommandMenuOpen(false)
    if (typingTimerRef.current) clearInterval(typingTimerRef.current)
    
    setSearchQuery('')
    setParsedIntents([])
    setIsParsing(false)
    setParseComplete(false)
    setIsTyping(true)

    let currentCharIndex = 0
    typingTimerRef.current = setInterval(() => {
      if (currentCharIndex < targetQuery.length) {
        setSearchQuery(targetQuery.substring(0, currentCharIndex + 1))
        currentCharIndex++
      } else {
        if (typingTimerRef.current) clearInterval(typingTimerRef.current)
        setIsTyping(false)
        setIsParsing(true)
        
        // Simulate step-by-step agent intent extraction
        setTimeout(() => {
          const tags = ['[Intent: Find Care]']
          if (targetQuery.toLowerCase().includes('pediatrician')) {
            tags.push('[Specialty: Pediatrics]')
          } else if (targetQuery.toLowerCase().includes('cut')) {
            tags.push('[Triage: Wound Care]')
          } else if (targetQuery.toLowerCase().includes('er')) {
            tags.push('[Triage: Emergent]')
          }
          setParsedIntents([...tags])
        }, 600)

        setTimeout(() => {
          const tags = ['[Intent: Find Care]']
          if (targetQuery.toLowerCase().includes('pediatrician')) {
            tags.push('[Specialty: Pediatrics]')
            tags.push('[Constraint: Open Post-19:00]')
          } else if (targetQuery.toLowerCase().includes('cut')) {
            tags.push('[Triage: Wound Care]')
            tags.push('[Facility: Urgent Care]')
          } else if (targetQuery.toLowerCase().includes('er')) {
            tags.push('[Triage: Emergent]')
            tags.push('[Constraint: Low Wait Queue]')
          } else {
            tags.push('[Constraint: Nearest Location]')
          }
          setParsedIntents([...tags])
        }, 1200)

        setTimeout(() => {
          setIsParsing(false)
          setParseComplete(true)
        }, 2000)
      }
    }, 40)
  }

  const handleSelectCommand = (index: number) => {
    const commands = [
      "Pediatrician open past 7pm nearby",
      "Urgent care clinic for deep cut",
      "Nearest ER with low wait time",
      "Diagnostic lab with rapid PCR testing"
    ]
    runSearchDemo(commands[index])
  }

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!searchQuery) return
    runSearchDemo(searchQuery)
  }

  // Animation timeline values based on time (0s - 12s)
  const isMapPulsing = time >= 0 && time < 2
  const mapScale = 1.0 + (time < 2 ? (time / 2) * 0.015 : 0.015 - ((time - 2) / 10) * 0.015)

  // Travelers move from 2s to 8s (progress is 0 to 1)
  const showTravelers = time >= 2 && time < 8.2
  const travelProgress = Math.max(0, Math.min(1, (time - 2) / 6))
  const showOverlays = time >= 4 && time < 8

  // Coordinates computed by interpolation
  const carPos = interpolatePath(CAR_PATH, travelProgress)
  const bikePos = interpolatePath(BIKE_PATH, travelProgress)
  const joggerPos = interpolatePath(JOGGER_PATH, travelProgress)
  const familyPos = interpolatePath(FAMILY_PATH, travelProgress)

  // Ripple arrivals occur between 8s and 10s
  const showRipples = time >= 8 && time < 10
  const rippleScale = 1.0 + ((time - 8) / 2) * 0.8
  const rippleOpacity = 1.0 - (time - 8) / 2

  // Success banner active from 10s to 11.8s
  const showSuccess = time >= 10 && time < 11.8

  return (
    <div className="bg-[#061219] min-h-screen relative flex flex-col font-static overflow-x-hidden select-none text-[#E2F1F5] selection:bg-[#48F6C1]/30">
      <LoginModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} defaultTab={modalTab} />

      {/* Modern High-End Header with Logo Palette & Blue Accents */}
      <header className="w-full border-b border-[#132A37]/80 bg-[#061219]/90 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-3 min-[360px]:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-1.5 min-[360px]:gap-3">
            <div className="w-8 h-8 min-[360px]:w-9 min-[360px]:h-9 rounded-lg overflow-hidden border border-[#1C4659]/50 flex-none shadow-sm">
              <img src="/logo.png" alt="MediCoord AI Logo" className="w-full h-full object-cover" />
            </div>
            <span className="text-xs min-[360px]:text-label-md font-bold tracking-wide text-white uppercase hidden min-[360px]:inline">
              MediCoord<span className="hidden min-[450px]:inline"> AI</span>
            </span>
          </div>

          <div className="flex items-center gap-3 min-[360px]:gap-6">
            {user ? (
              <button
                onClick={() => navigate('/app')}
                className="text-xs min-[360px]:text-label-md font-medium text-[#7AA0B0] hover:text-[#00D2FF] transition-colors cursor-pointer"
              >
                Go to App
              </button>
            ) : (
              <button onClick={openSignIn} className="text-xs min-[360px]:text-label-md font-medium text-[#7AA0B0] hover:text-[#00D2FF] transition-colors cursor-pointer">
                Sign in
              </button>
            )}
            <button
              onClick={user ? () => navigate('/app') : openSignUp}
              className="px-2.5 py-1.5 min-[360px]:px-4 min-[360px]:py-2 text-xs min-[360px]:text-label-md font-semibold text-[#061219] rounded-lg bg-[#48F6C1] hover:bg-[#3ce0ad] shadow-sm transition-all duration-250 cursor-pointer active:scale-95"
            >
              Get started
            </button>
          </div>
        </div>
      </header>

      {/* Main Container: Split Hero section */}
      <main className="flex-1 w-full flex items-center justify-center relative overflow-hidden">
        <div className="max-w-7xl w-full mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12 px-6 py-12 lg:py-20 items-center">
          
          {/* Left Column: Command & Input Workspace */}
          <div className="lg:col-span-5 flex flex-col gap-6 relative z-20">
            <div className="inline-flex items-center self-start gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#00D2FF]/10 text-[#00D2FF] border border-[#00D2FF]/20 tracking-wider uppercase">
              <Sparkle className="w-3.5 h-3.5" weight="fill" />
              AI Health Routing · Toronto
            </div>

            <h1 className="text-display-md lg:text-[56px] text-white leading-[1.05] tracking-tight font-extrabold">
              Know where <br/>
              to go, <br/>
              before you go.
            </h1>

            <p className="text-body-md text-[#85A4B1] max-w-lg leading-relaxed">
              Describe your symptoms. We'll find the nearest clinic, urgent care, or ER that can help — with real wait times and directions.
            </p>

            {/* Unified Omni-Input Box Workspace */}
            <div className="relative w-full max-w-lg mt-2">
              <form onSubmit={handleFormSubmit} className="relative z-20">
                <div className="flex items-center w-full h-14 pl-4 pr-2.5 rounded-xl border border-[#1C4659]/65 bg-[#0A1D27]/90 backdrop-blur-xl shadow-lg focus-within:border-[#48F6C1] focus-within:ring-2 focus-within:ring-[#48F6C1]/10 transition-all duration-300">
                  <MagnifyingGlass className="w-5 h-5 text-[#7AA0B0] flex-none mr-2.5" />
                  
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value)
                      setParseComplete(false)
                    }}
                    placeholder={PLACEHOLDERS[placeholderIndex]}
                    disabled={isTyping}
                    className="flex-1 h-full bg-transparent text-white placeholder-[#7AA0B0]/60 outline-none text-body-md"
                  />

                  {/* Inline Command indicator */}
                  <button
                    type="button"
                    onClick={() => setIsCommandMenuOpen((prev) => !prev)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-[#1C4659]/60 bg-[#0A1D27]/40 text-xs font-mono text-[#7AA0B0] hover:bg-[#0A1D27]/90 hover:text-white transition-colors"
                  >
                    <Command className="w-3 h-3" />
                    <span>K</span>
                  </button>

                  <button
                    type="submit"
                    className="ml-2.5 h-9 px-4 text-label-md font-semibold text-[#061219] rounded-lg bg-[#48F6C1] hover:bg-[#3ce0ad] shadow-sm transition-all duration-250 cursor-pointer active:scale-95"
                  >
                    Parse
                  </button>
                </div>
              </form>

              {/* Command Menu Dropdown */}
              <AnimatePresence>
                {isCommandMenuOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 2 }}
                    exit={{ opacity: 0, y: 6 }}
                    className="absolute left-0 right-0 top-full mt-1.5 z-30 rounded-xl border border-[#1A3F4F] bg-[#0A1D27] shadow-2xl p-2.5 text-[#E2F1F5]"
                  >
                    <div className="px-2.5 py-1.5 text-[11px] font-mono text-[#7AA0B0] uppercase tracking-wider border-b border-[#1C4659]/40 mb-1.5 flex items-center justify-between">
                      <span>Quick Intents Command Menu</span>
                      <span>ESC to close · ↑↓ to navigate</span>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      {[
                        { label: "🚑 Locate Nearest ER Emergency Room", desc: "Instantly checks wait times and routing" },
                        { label: "🩺 Search Pediatrician Nearby", desc: "Filters for pediatric specialty open after hours" },
                        { label: "🩹 Route Urgent Care for Deep Cut", desc: "Finds clinic equipped for lacerations" },
                        { label: "🧪 Locate Diagnostic Lab (PCR)", desc: "Finds labs with rapid PCR processing" }
                      ].map((cmd, idx) => (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => handleSelectCommand(idx)}
                          className={`w-full text-left px-3 py-2 rounded-lg flex flex-col text-body-md transition-colors ${
                            selectedCommandIndex === idx ? 'bg-[#132E3C] border-l-2 border-[#48F6C1] pl-2.5' : 'hover:bg-[#132E3C]/40'
                          }`}
                        >
                          <span className="font-semibold text-white text-sm">{cmd.label}</span>
                          <span className="text-xs text-[#7AA0B0]">{cmd.desc}</span>
                        </button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Sample Queries Chips */}
              <div className="flex flex-wrap gap-2 mt-3.5">
                <span className="text-xs text-[#7AA0B0] self-center mr-1">Try:</span>
                {SAMPLE_CHIPS.map((chip, i) => (
                  <button
                    key={i}
                    onClick={() => runSearchDemo(chip.query)}
                    className="px-3 py-1 rounded-full text-xs border border-[#1C4659]/60 bg-[#0A1D27]/40 text-[#7AA0B0] hover:bg-[#0A1D27]/90 hover:text-[#48F6C1] hover:border-[#48F6C1]/40 shadow-sm transition-all duration-200 cursor-pointer"
                  >
                    {chip.text}
                  </button>
                ))}
              </div>

              {/* Asynchronous Streaming Preview Box */}
              <AnimatePresence>
                {(isTyping || isParsing || parsedIntents.length > 0 || parseComplete) && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 10 }}
                    className="mt-5 w-full rounded-xl border border-[#1C4659]/60 bg-[#0A1D27]/95 shadow-xl p-5 flex flex-col gap-3 relative overflow-hidden"
                  >
                    {/* Header line */}
                    <div className="flex items-center justify-between border-b border-[#1C4659]/40 pb-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 rounded-full bg-[#48F6C1] animate-pulse" />
                        <span className="text-xs font-mono font-bold text-white uppercase tracking-wider">Checking availability...</span>
                      </div>
                      {parseComplete && (
                        <span className="text-xs font-semibold text-[#48F6C1] bg-[#48F6C1]/10 px-2 py-0.5 rounded-md flex items-center gap-1 border border-[#48F6C1]/20">
                          <Check className="w-3.5 h-3.5" /> Checked
                        </span>
                      )}
                    </div>

                    {/* Simulation stream details */}
                    <div className="flex flex-col gap-2 min-h-24">
                      {isTyping && (
                        <p className="text-xs font-mono text-[#7AA0B0] italic">Typing search prompt...</p>
                      )}
                      
                      {isParsing && (
                        <div className="flex items-center gap-2 text-xs font-mono text-white">
                          <CircleNotch className="w-4 h-4 text-[#48F6C1] animate-spin" />
                          <span>Checking nearby clinics, urgent cares, and wait times...</span>
                        </div>
                      )}

                      {/* Displaying extracted chips */}
                      <div className="flex flex-wrap gap-2.5 mt-1">
                        {parsedIntents.map((tag, idx) => (
                          <motion.span
                            key={idx}
                            initial={{ scale: 0.85, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            className="px-2.5 py-1 rounded bg-[#132E3C] text-[11px] font-mono font-bold text-[#48F6C1] border border-[#1C4659]/60"
                          >
                            {tag}
                          </motion.span>
                        ))}
                      </div>

                      {parseComplete && (
                        <motion.div
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="flex flex-col gap-2.5 mt-2"
                        >
                          <p className="text-xs text-[#85A4B1] leading-relaxed">
                            Found nearby facilities matching your situation. Results are ready in MediCoord AI.
                          </p>
                          <button
                            onClick={() => navigate('/app')}
                            className="self-start inline-flex items-center gap-1.5 px-4.5 py-2 text-xs font-bold text-[#061219] bg-[#48F6C1] hover:bg-[#3ce0ad] rounded-lg shadow-sm transition-all duration-200 active:scale-95 cursor-pointer"
                          >
                            Open MediCoord AI
                            <ArrowRight className="w-3.5 h-3.5" />
                          </button>
                        </motion.div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>

          {/* Right Column: Hero Animation Loop Canvas (Increased Height & Seamless Blending) */}
          <div className="lg:col-span-7 flex justify-center items-center relative min-h-[500px] lg:min-h-[640px] w-full">
            <div className="relative w-full h-[540px] lg:h-[620px] rounded-2xl overflow-hidden">
              
              {/* Map background image with subtle respirating scaling */}
              <div 
                className="w-full h-full overflow-hidden relative z-0"
                style={{
                  transform: `scale(${mapScale})`,
                  transition: 'transform 0.05s linear'
                }}
              >
                <img 
                  src="/base_map_canvas.png" 
                  alt="City Map Viewport" 
                  className="w-full h-full object-cover select-none filter brightness-90 contrast-105 saturate-[0.9]"
                />

                {/* SVG Route Trails Layer */}
                <svg 
                  className="absolute inset-0 w-full h-full z-10 pointer-events-none"
                  viewBox="0 0 100 100" 
                  preserveAspectRatio="none"
                >
                  {/* Car route path (Mint Green) */}
                  <path
                    d="M 10 92 L 22 78 L 28 70 L 28 50"
                    fill="none"
                    stroke="#48F6C1"
                    strokeWidth="0.8"
                    strokeDasharray="100"
                    strokeDashoffset={showTravelers ? 100 - travelProgress * 100 : 100}
                    className="transition-all duration-100 ease-out"
                    opacity="0.8"
                  />
                  {/* Bike route path (Electric Cyber Blue - `#00D2FF` variant) */}
                  <path
                    d="M 48 92 L 48 72 L 58 60 L 58 51"
                    fill="none"
                    stroke="#00D2FF"
                    strokeWidth="0.8"
                    strokeDasharray="100"
                    strokeDashoffset={showTravelers ? 100 - travelProgress * 100 : 100}
                    className="transition-all duration-100 ease-out"
                    opacity="0.8"
                  />
                  {/* Jogger route path (Lighter Mint) */}
                  <path
                    d="M 92 90 L 81 79 L 81 54"
                    fill="none"
                    stroke="#5CEBBA"
                    strokeWidth="0.8"
                    strokeDasharray="100"
                    strokeDashoffset={showTravelers ? 100 - travelProgress * 100 : 100}
                    className="transition-all duration-100 ease-out"
                    opacity="0.8"
                  />
                  {/* Family route path (Muted Teal) */}
                  <path
                    d="M 64 22 L 64 40 L 58 46 L 58 51"
                    fill="none"
                    stroke="#2E8EA5"
                    strokeWidth="0.8"
                    strokeDasharray="100"
                    strokeDashoffset={showTravelers ? 100 - travelProgress * 100 : 100}
                    className="transition-all duration-100 ease-out"
                    opacity="0.8"
                  />
                </svg>

                {/* Pulsating Street Lines grid indicator */}
                <div 
                  className={`absolute inset-0 bg-[#2B7A8C]/5 mix-blend-overlay pointer-events-none transition-opacity duration-1000 ${
                    isMapPulsing ? 'opacity-80' : 'opacity-20'
                  }`} 
                />
              </div>

              {/* Edge Gradient Blending to make the canvas look seamless inside the dark page */}
              <div className="absolute left-0 top-0 bottom-0 w-20 bg-gradient-to-r from-[#061219] to-transparent z-20 pointer-events-none" />
              <div className="absolute right-0 top-0 bottom-0 w-20 bg-gradient-to-l from-[#061219] to-transparent z-20 pointer-events-none" />
              <div className="absolute left-0 right-0 top-0 h-20 bg-gradient-to-b from-[#061219] to-transparent z-20 pointer-events-none" />
              <div className="absolute left-0 right-0 bottom-0 h-20 bg-gradient-to-t from-[#061219] to-transparent z-20 pointer-events-none" />

              {/* FACILITY PIN MARKERS OVERLAY */}
              
              {/* General Hospital */}
              <div 
                className="absolute z-20"
                style={HOSPITAL_PIN}
              >
                {/* Ripple Circle (Mint color) */}
                {showRipples && (
                  <div 
                    className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#48F6C1] bg-[#48F6C1]/10 pointer-events-none"
                    style={{
                      width: `${rippleScale * 45}px`,
                      height: `${rippleScale * 45}px`,
                      opacity: rippleOpacity,
                      transition: 'all 0.05s linear'
                    }}
                  />
                )}
                {/* Map pin */}
                <div className="absolute -translate-x-1/2 -translate-y-[85%] flex flex-col items-center">
                  <div className="bg-[#28A684] text-white p-1 rounded-full border border-white shadow-md">
                    <MapPin className="w-4.5 h-4.5" weight="fill" />
                  </div>
                  <div className="mt-1 bg-[#0A1A21]/90 backdrop-blur-sm border border-[#1C4659]/50 px-1.5 py-0.5 rounded text-[10px] font-bold text-white whitespace-nowrap shadow-sm">
                    General Hospital
                  </div>
                </div>
              </div>

              {/* Urgent Care Clinic */}
              <div 
                className="absolute z-20"
                style={CLINIC_PIN}
              >
                {/* Ripple Circle (Blue color) */}
                {showRipples && (
                  <div 
                    className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#00D2FF] bg-[#00D2FF]/10 pointer-events-none"
                    style={{
                      width: `${rippleScale * 45}px`,
                      height: `${rippleScale * 45}px`,
                      opacity: rippleOpacity,
                      transition: 'all 0.05s linear'
                    }}
                  />
                )}
                {/* Map pin */}
                <div className="absolute -translate-x-1/2 -translate-y-[85%] flex flex-col items-center">
                  <div className="bg-[#00D2FF] text-[#061219] p-1 rounded-full border border-white shadow-md">
                    <MapPin className="w-4.5 h-4.5" weight="fill" />
                  </div>
                  <div className="mt-1 bg-[#0A1A21]/90 backdrop-blur-sm border border-[#1C4659]/50 px-1.5 py-0.5 rounded text-[10px] font-bold text-white whitespace-nowrap shadow-sm">
                    Urgent Care Clinic
                  </div>
                </div>
              </div>

              {/* Diagnostic Lab */}
              <div 
                className="absolute z-20"
                style={LAB_PIN}
              >
                {/* Ripple Circle */}
                {showRipples && (
                  <div 
                    className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#2E8EA5] bg-[#2E8EA5]/10 pointer-events-none"
                    style={{
                      width: `${rippleScale * 45}px`,
                      height: `${rippleScale * 45}px`,
                      opacity: rippleOpacity,
                      transition: 'all 0.05s linear'
                    }}
                  />
                )}
                {/* Map pin */}
                <div className="absolute -translate-x-1/2 -translate-y-[85%] flex flex-col items-center">
                  <div className="bg-[#195669] text-white p-1 rounded-full border border-white shadow-md">
                    <MapPin className="w-4.5 h-4.5" weight="fill" />
                  </div>
                  <div className="mt-1 bg-[#0A1A21]/90 backdrop-blur-sm border border-[#1C4659]/50 px-1.5 py-0.5 rounded text-[10px] font-bold text-white whitespace-nowrap shadow-sm">
                    Diagnostic Lab
                  </div>
                </div>
              </div>

              {/* TRAVELER NODES & OVERLAYS */}
              {showTravelers && (
                <>
                  {/* Car Traveler */}
                  <div 
                    className="absolute z-20 -translate-x-1/2 -translate-y-1/2 transition-all duration-100 ease-out"
                    style={{ left: carPos.left, top: carPos.top }}
                  >
                    <div className="relative">
                      {/* Car Marker Pin */}
                      <div className="w-7 h-7 rounded-full bg-[#48F6C1] text-[#061219] flex items-center justify-center border border-white shadow-lg shadow-[#48F6C1]/40">
                        <Car className="w-4 h-4" />
                      </div>
                      
                      {/* Floating overlay tracking above car */}
                      {showOverlays && (
                        <div className="absolute bottom-[115%] left-1/2 -translate-x-1/2 bg-[#061219]/95 backdrop-blur-md border border-[#48F6C1]/30 text-white text-[9px] font-mono px-2 py-1 rounded whitespace-nowrap flex items-center gap-1 shadow-lg pointer-events-none animate-bounce">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#48F6C1] animate-ping" />
                          <span>Routing ETA: 6m</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Bike Traveler (Electric Cyber Blue Variant) */}
                  <div 
                    className="absolute z-20 -translate-x-1/2 -translate-y-1/2 transition-all duration-100 ease-out"
                    style={{ left: bikePos.left, top: bikePos.top }}
                  >
                    <div className="relative">
                      <div className="w-7 h-7 rounded-full bg-[#00D2FF] text-[#061219] flex items-center justify-center border border-white shadow-lg shadow-[#00D2FF]/40">
                        <Bicycle className="w-4 h-4" />
                      </div>

                      {showOverlays && (
                        <div className="absolute bottom-[115%] left-1/2 -translate-x-1/2 bg-[#061219]/95 backdrop-blur-md border border-[#00D2FF]/30 text-white text-[9px] font-mono px-2 py-1 rounded whitespace-nowrap flex flex-col gap-0.5 items-center shadow-lg pointer-events-none">
                          <span>Flat terrain optimized</span>
                          <span className="text-[7.5px] opacity-75">ETA: 11m</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Jogger Traveler */}
                  <div 
                    className="absolute z-20 -translate-x-1/2 -translate-y-1/2 transition-all duration-100 ease-out"
                    style={{ left: joggerPos.left, top: joggerPos.top }}
                  >
                    <div className="relative">
                      <div className="w-7 h-7 rounded-full bg-[#5CEBBA] text-[#061219] flex items-center justify-center border border-white shadow-lg shadow-[#5CEBBA]/30">
                        <User className="w-4 h-4" />
                      </div>
                    </div>
                  </div>

                  {/* Family Traveler */}
                  <div 
                    className="absolute z-20 -translate-x-1/2 -translate-y-1/2 transition-all duration-100 ease-out"
                    style={{ left: familyPos.left, top: familyPos.top }}
                  >
                    <div className="relative">
                      <div className="w-7 h-7 rounded-full bg-[#2E8EA5] text-white flex items-center justify-center border border-white shadow-lg shadow-[#2E8EA5]/30">
                        <User className="w-4 h-4" />
                      </div>
                    </div>
                  </div>
                </>
              )}

              {/* SUCCESS BANNER OVERLAY */}
              <AnimatePresence>
                {showSuccess && (
                  <motion.div
                    initial={{ opacity: 0, y: -20, x: '-50%' }}
                    animate={{ opacity: 1, y: 12, x: '-50%' }}
                    exit={{ opacity: 0, y: -20, x: '-50%' }}
                    className="absolute top-0 left-1/2 z-30 w-[85%] rounded-xl border border-[#48F6C1]/30 bg-[#061219]/95 backdrop-blur-xl p-3 flex items-center justify-between shadow-2xl"
                  >
                    <div className="flex items-center gap-2.5">
                      <div className="w-8 h-8 rounded-full bg-[#48F6C1]/20 text-[#48F6C1] flex items-center justify-center border border-[#48F6C1]/30">
                        <ShieldCheck className="w-5 h-5" />
                      </div>
                      <div className="flex flex-col">
                        <span className="text-[11px] font-bold text-white tracking-wide uppercase">Facility matched</span>
                        <span className="text-[9.5px] font-mono text-[#48F6C1]">Routed to the best available option near you</span>
                      </div>
                    </div>
                    <span className="text-[10px] font-mono font-semibold bg-[#48F6C1]/10 text-[#48F6C1] px-2 py-0.5 rounded border border-[#48F6C1]/20">
                      SECURE GATEWAY
                    </span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Live HUD System Status */}
              <div className="absolute bottom-3 left-3 z-20 bg-[#061219]/80 backdrop-blur-sm border border-[#1C4659]/50 rounded-md px-2 py-1 flex items-center gap-1.5 pointer-events-none">
                <span className="w-2 h-2 rounded-full bg-[#48F6C1] animate-ping" />
                <span className="text-[9px] font-mono text-white tracking-wider uppercase">SECURE NETWORK OK</span>
              </div>
            </div>
          </div>

        </div>
      </main>

      {/* Strategic Positioning & Technical Edge Section */}
      <section className="max-w-7xl mx-auto px-6 py-16 lg:py-24 border-t border-[#132A37]/80 w-full flex flex-col gap-12 relative z-20">
        <div className="flex flex-col gap-3">
          <div className="text-xs font-bold uppercase tracking-widest text-[#00D2FF]">Why MediCoord AI</div>
          <h2 className="text-3xl lg:text-4xl font-extrabold text-white">The right care, without the guesswork</h2>
          <p className="text-[#85A4B1] max-w-xl text-sm leading-relaxed">
            Most people don't know whether to go to urgent care, the ER, or their family doctor. MediCoord AI figures that out for you.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Card 1: Strategic Positioning & Value */}
          <div className="relative border border-[#1C4659]/50 bg-[#0A1D27]/80 rounded-2xl p-8 flex flex-col gap-5 shadow-xl hover:border-[#00D2FF]/60 transition-all duration-300">
            <div className="w-12 h-12 rounded-xl bg-[#00D2FF]/10 text-[#00D2FF] border border-[#00D2FF]/20 flex items-center justify-center">
              <Sparkle className="w-6 h-6 animate-pulse" />
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="text-xl font-bold text-white">Real wait times, not estimates</h3>
              <span className="text-xs font-mono font-bold text-[#00D2FF] uppercase tracking-wider">Live Queue Data · Toronto Facilities</span>
              <p className="text-sm text-[#85A4B1] leading-relaxed mt-2">
                Live queue data from Toronto facilities so you know the best place to go right now — not just the nearest one.
              </p>
              <p className="text-sm text-[#85A4B1] leading-relaxed mt-1">
                The closest clinic isn't always the fastest option. We combine travel time and current wait queues to find the one where you'll be seen soonest.
              </p>
            </div>
            <div className="mt-auto pt-6 border-t border-[#1C4659]/30 flex items-center justify-between">
              <span className="text-xs text-[#7AA0B0] font-mono">See multi-facility load balancing:</span>
              <Link
                to="/sandbox"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-[#061219] bg-[#00D2FF] hover:bg-[#00b4db] rounded-lg shadow-sm transition-all duration-200 active:scale-95 cursor-pointer"
              >
                Launch Sandbox Mode
                <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>

          {/* Card 2: Technical Architecture & Prowess */}
          <div className="relative border border-[#1C4659]/50 bg-[#0A1D27]/80 rounded-2xl p-8 flex flex-col gap-5 shadow-xl hover:border-[#48F6C1]/60 transition-all duration-300">
            <div className="w-12 h-12 rounded-xl bg-[#48F6C1]/10 text-[#48F6C1] border border-[#48F6C1]/20 flex items-center justify-center">
              <Stethoscope className="w-6 h-6" />
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="text-xl font-bold text-white">Your symptoms stay private</h3>
              <span className="text-xs font-mono font-bold text-[#48F6C1] uppercase tracking-wider">Session-Only · Never Stored · Never Trained</span>
              <p className="text-sm text-[#85A4B1] leading-relaxed mt-2">
                Your descriptions are never stored beyond your session or used to train any AI model. No appointment, no referral, no account required to try it.
              </p>
              <p className="text-sm text-[#85A4B1] leading-relaxed mt-1">
                MediCoord AI is built on real Canadian public health data — real hospital locations, real facility types, and real routing times from Toronto's transit and road network.
              </p>
            </div>
            <div className="mt-auto pt-6 border-t border-[#1C4659]/30 flex flex-wrap gap-2 text-xs font-mono text-[#7AA0B0]">
              <span className="px-2.5 py-1 rounded bg-[#132E3C]/50 border border-[#1C4659]/65">Graph RAG</span>
              <span className="px-2.5 py-1 rounded bg-[#132E3C]/50 border border-[#1C4659]/65">MCP Telemetry</span>
              <span className="px-2.5 py-1 rounded bg-[#132E3C]/50 border border-[#1C4659]/65">Real-Time OSRM</span>
            </div>
          </div>
        </div>
      </section>

      {/* Interactive Operational Workflow Section */}
      <section className="max-w-7xl mx-auto px-6 py-16 lg:py-24 border-t border-[#132A37]/80 w-full flex flex-col gap-12 relative z-20">
        <div className="flex flex-col gap-3">
          <div className="text-xs font-bold uppercase tracking-widest text-[#48F6C1]">How it works</div>
          <h2 className="text-3xl lg:text-4xl font-extrabold text-white">From symptom to facility in seconds</h2>
          <p className="text-[#85A4B1] max-w-xl text-sm leading-relaxed">
            Every request goes through three steps — description, assessment, and routing — so you always get the most relevant recommendation.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-stretch">
          {/* Step Selector Tabs */}
          <div className="lg:col-span-4 flex flex-col gap-4 w-full">
            {HOW_IT_WORKS_STEPS.map((step) => {
              const Icon = step.icon;
              return (
                <button
                  key={step.id}
                  onClick={() => setActiveStep(step.id)}
                  className={`w-full text-left p-5 rounded-xl border transition-all duration-300 cursor-pointer flex flex-col gap-1.5 ${
                    activeStep === step.id
                      ? "border-[#48F6C1] bg-[#132E3C]/50 shadow-lg shadow-[#48F6C1]/5"
                      : "border-[#1C4659]/40 bg-[#0A1D27]/40 hover:border-[#1C4659]/80 hover:bg-[#0A1D27]/80"
                  }`}
                >
                  <span className={`text-[10px] font-mono font-bold uppercase tracking-wider ${
                    activeStep === step.id ? "text-[#48F6C1]" : "text-[#7AA0B0]"
                  }`}>
                    {step.tagline}
                  </span>
                  <div className="flex items-center gap-2">
                    <Icon className={`w-4.5 h-4.5 ${activeStep === step.id ? "text-[#48F6C1]" : "text-[#85A4B1]"}`} />
                    <h4 className="text-md font-bold text-white">{step.title}</h4>
                  </div>
                  <p className="text-xs text-[#85A4B1] leading-relaxed mt-1">{step.desc}</p>
                </button>
              );
            })}
          </div>

          {/* Interactive Simulation Panel */}
          <div className="lg:col-span-8 w-full border border-[#1C4659]/60 bg-[#0A1D27]/90 backdrop-blur-xl rounded-2xl p-6 h-full flex flex-col gap-5 relative overflow-hidden shadow-2xl">
            {/* Header/Status Bar */}
            <div className="flex items-center justify-between border-b border-[#1C4659]/40 pb-4">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#48F6C1] animate-ping" />
                <span className="text-xs font-mono font-bold text-white uppercase tracking-widest">
                  {activeStep === 1 && "Listening to your description — ACTIVE"}
                  {activeStep === 2 && "Assessing clinical context — ACTIVE"}
                  {activeStep === 3 && "Calculating routes and wait times — ACTIVE"}
                </span>
              </div>
              <span className="text-[10px] font-mono text-[#7AA0B0] bg-[#132E3C]/60 px-2.5 py-1 rounded border border-[#1C4659]/50">
                {`STAGE ${activeStep} / 3`}
              </span>
            </div>

            {/* Interactive Showcase Content */}
            <AnimatePresence mode="wait">
              {activeStep === 1 && (
                <motion.div
                  key="step1"
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -15 }}
                  transition={{ duration: 0.3 }}
                  className="flex flex-col gap-4 flex-1 justify-center"
                >
                  <div className="flex flex-col gap-3 font-mono text-xs">
                    {/* Patient Speech Input */}
                    <div className="bg-[#061219]/90 border border-[#1C4659]/60 rounded-xl p-3.5 flex flex-col gap-2">
                      <div className="flex justify-between items-center text-[10px] text-[#7AA0B0] border-b border-[#1C4659]/30 pb-1.5">
                        <span>patient_speech_input:</span>
                        <span className="text-[#00D2FF]">natural_language</span>
                      </div>
                      <span className="text-white text-body-md font-sans italic">
                        "My child woke up with a very high fever, they are breathing faster than normal and won't drink anything."
                      </span>
                    </div>

                    {/* Graph RAG Entity Recognition */}
                    <div className="flex flex-col gap-2.5 bg-[#061219]/60 border border-[#1C4659]/40 rounded-xl p-3.5">
                      <span className="text-[10px] text-[#7AA0B0] uppercase tracking-wider">Graph RAG Entity Recognition & Relations:</span>
                      <div className="flex flex-wrap gap-2">
                        <span className="px-2 py-0.5 rounded bg-[#00D2FF]/10 text-[#00D2FF] border border-[#00D2FF]/20 text-[10px]">
                          [Patient: Pediatric]
                        </span>
                        <span className="px-2 py-0.5 rounded bg-[#48F6C1]/10 text-[#48F6C1] border border-[#48F6C1]/20 text-[10px]">
                          [Symptom: Pyrexia/Fever]
                        </span>
                        <span className="px-2 py-0.5 rounded bg-[#48F6C1]/10 text-[#48F6C1] border border-[#48F6C1]/20 text-[10px]">
                          [Symptom: Tachypnea/Rapid Breathing]
                        </span>
                        <span className="px-2 py-0.5 rounded bg-[#FF7B93]/10 text-[#FF7B93] border border-[#FF7B93]/20 text-[10px]">
                          [Risk: Dehydration Indicator]
                        </span>
                      </div>
                    </div>

                    {/* AI Prompted Follow-up Question */}
                    <div className="bg-[#132E3C]/30 border border-[#48F6C1]/30 rounded-xl p-3.5 flex flex-col gap-1.5">
                      <span className="text-[10px] text-[#48F6C1] uppercase tracking-wider font-bold">Generated Clinical Follow-up:</span>
                      <p className="text-white font-sans text-body-md">
                        "I've recorded the high fever and fast breathing. Is your child unusually sleepy, or are you noticing a rash or pulling in of their chest muscles when breathing?"
                      </p>
                    </div>
                  </div>
                </motion.div>
              )}

              {activeStep === 2 && (
                <motion.div
                  key="step2"
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -15 }}
                  transition={{ duration: 0.3 }}
                  className="flex flex-col gap-4 flex-1 justify-center"
                >
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Severity scoring details */}
                    <div className="flex flex-col gap-3 p-4 rounded-xl border border-[#1C4659]/50 bg-[#061219]/60 font-mono text-xs">
                      <span className="text-[10px] text-[#7AA0B0] uppercase tracking-wider border-b border-[#1C4659]/40 pb-1.5">
                        Triage Score Calculation
                      </span>
                      <div className="flex justify-between items-center">
                        <span>Respiratory Rate Index:</span>
                        <span className="text-[#FF7B93] font-bold">CRITICAL (+3)</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span>Pediatric Age Factor:</span>
                        <span className="text-[#00D2FF] font-bold">MODERATE (+2)</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span>Fluid Intake/Dehydration:</span>
                        <span className="text-[#48F6C1] font-bold">EVALUATED (+1)</span>
                      </div>
                      <div className="border-t border-[#1C4659]/40 pt-2 flex justify-between items-center text-white font-bold">
                        <span>Composite Score:</span>
                        <span className="px-2 py-0.5 rounded bg-[#FF7B93]/20 border border-[#FF7B93]/40">
                          ESI LEVEL 2
                        </span>
                      </div>
                    </div>

                    {/* Medical Interpretation panel */}
                    <div className="flex flex-col gap-3 p-4 rounded-xl border border-[#1C4659]/50 bg-[#061219]/60 font-mono text-xs">
                      <span className="text-[10px] text-[#7AA0B0] uppercase tracking-wider border-b border-[#1C4659]/40 pb-1.5">
                        Medical Interpretation
                      </span>
                      <p className="text-white font-sans text-xs leading-relaxed">
                        The agent correlates the user's natural description of "breathing faster" and "won't drink" with pediatric clinical graphs to identify potential tachypnea-induced dehydration.
                      </p>
                      <p className="text-[#85A4B1] font-sans text-xs leading-relaxed">
                        Relationship mapped: <br />
                        <span className="text-[#48F6C1]">Tachypnea + Decreased Intake ➔ Pediatric Respiratory Distress Protocol</span>.
                      </p>
                      <span className="text-[#FF7B93] text-[10px] font-bold uppercase tracking-wider mt-1 block">
                        ➔ Emergency / Urgent Care Referral Required
                      </span>
                    </div>
                  </div>
                </motion.div>
              )}

              {activeStep === 3 && (
                <motion.div
                  key="step3"
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -15 }}
                  transition={{ duration: 0.3 }}
                  className="flex flex-col gap-4 flex-1 justify-center"
                >
                  <div className="flex flex-col gap-3 font-mono text-xs">
                    {/* Routing logic details */}
                    <span className="text-[10px] text-[#7AA0B0] uppercase tracking-wider">
                      Comparison: Straight Distance vs. Dynamic Care ETA Routing
                    </span>

                    <div className="overflow-x-auto">
                      <table className="w-full text-left border-collapse text-[11px]">
                        <thead>
                          <tr className="border-b border-[#1C4659]/50 text-[#7AA0B0]">
                            <th className="py-2 pr-2">FACILITY</th>
                            <th className="py-2 px-2">STRAIGHT DISTANCE</th>
                            <th className="py-2 px-2">TRANSIT DURATION</th>
                            <th className="py-2 px-2">ACTIVE WAIT QUEUE</th>
                            <th className="py-2 pl-2 text-white">TOTAL TIME TO CARE</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#1C4659]/30 text-white">
                          <tr>
                            <td className="py-2.5 pr-2 font-sans font-bold">General Hospital (Pediatric Wing)</td>
                            <td className="py-2.5 px-2 text-[#7AA0B0]">4.2 km</td>
                            <td className="py-2.5 px-2">8 mins (OSRM API)</td>
                            <td className="py-2.5 px-2 text-[#48F6C1]">15 mins</td>
                            <td className="py-2.5 pl-2 text-[#48F6C1] font-bold">23 mins total (RECOMMENDED)</td>
                          </tr>
                          <tr className="opacity-70">
                            <td className="py-2.5 pr-2 font-sans font-bold">Urgent Care Clinic A</td>
                            <td className="py-2.5 px-2 text-[#7AA0B0]">1.5 km (Closest)</td>
                            <td className="py-2.5 px-2">5 mins (OSRM API)</td>
                            <td className="py-2.5 px-2 text-[#FF7B93]">60 mins</td>
                            <td className="py-2.5 pl-2 text-[#FF7B93]">65 mins total</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>

                    <div className="bg-[#132E3C]/30 border border-[#48F6C1]/30 rounded-xl p-3.5 flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-[#48F6C1]/20 text-[#48F6C1] flex items-center justify-center shrink-0 border border-[#48F6C1]/20">
                        <Check className="w-4 h-4" />
                      </div>
                      <p className="text-white font-sans text-xs leading-normal">
                        <strong>Dispatch Decision:</strong> General Hospital selected. Standard straight-line distance mapping would have routed the patient to Clinic A, resulting in <strong>42 minutes of extra waiting time</strong>.
                      </p>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </section>

      {/* HowTo structured data for the "How it works" section above */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": "How MediCoord AI routes you to the right facility",
            "step": HOW_IT_WORKS_STEPS.map((step) => ({
              "@type": "HowToStep",
              "name": step.title.replace(/^\d+\.\s*/, ''),
              "text": step.desc
            }))
          })
        }}
      />

      {/* FAQ Section */}
      <section className="max-w-7xl mx-auto px-6 py-16 lg:py-24 border-t border-[#132A37]/80 w-full flex flex-col gap-10 relative z-20">
        <div className="flex flex-col gap-3">
          <div className="text-xs font-bold uppercase tracking-widest text-[#00D2FF]">FAQ</div>
          <h2 className="text-3xl lg:text-4xl font-extrabold text-white">Common questions</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {FAQ_ITEMS.map((item) => (
            <div key={item.q} className="flex flex-col gap-2 border border-[#1C4659]/50 bg-[#0A1D27]/80 rounded-2xl p-6">
              <h3 className="text-sm font-bold text-white">{item.q}</h3>
              <p className="text-sm text-[#85A4B1] leading-relaxed">{item.a}</p>
            </div>
          ))}
        </div>
      </section>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": FAQ_ITEMS.map((item) => ({
              "@type": "Question",
              "name": item.q,
              "acceptedAnswer": { "@type": "Answer", "text": item.a }
            }))
          })
        }}
      />

      {/* Modern Contextual Cookie Banner */}
      <AnimatePresence>
        {cookieBannerOpen && (
          <motion.div
            initial={{ opacity: 0, y: 30, x: '-50%' }}
            animate={{ opacity: 1, y: 0, x: '-50%' }}
            exit={{ opacity: 0, y: 30, x: '-50%' }}
            transition={{ duration: 0.8 }}
            className="fixed bottom-16 left-1/2 z-40 w-[92%] max-w-xl bg-[#0A1D27]/95 backdrop-blur-2xl border border-[#1C4659]/80 rounded-2xl shadow-2xl flex flex-col p-4.5 gap-3.5 transition-all text-[#E2F1F5]"
          >
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-[#48F6C1]/20 text-[#48F6C1] flex items-center justify-center border border-[#48F6C1]/10 flex-none animate-pulse">
                  <Info className="w-4.5 h-4.5" />
                </div>
                <div className="flex flex-col">
                  <span className="text-sm font-bold text-white leading-tight">Privacy & Performance Settings</span>
                  <span className="text-xs text-[#85A4B1]">Optimize routing parameters and save maps coordinate preferences.</span>
                </div>
              </div>

              <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
                <button
                  onClick={() => setShowPreferences(!showPreferences)}
                  className="px-3 py-1.5 rounded-lg border border-[#1C4659]/65 hover:bg-[#132E3C]/40 text-xs font-semibold text-[#7AA0B0] hover:text-white transition-colors flex items-center gap-1 cursor-pointer"
                >
                  Preferences
                  {showPreferences ? <CaretUp className="w-3 h-3" /> : <CaretDown className="w-3 h-3" />}
                </button>

                <button
                  onClick={() => {
                    const settings: CookieSettings = { zoom: true, history: true, analytics: true }
                    setCookieSettings(settings)
                    persistConsent(settings)
                    setCookieBannerOpen(false)
                  }}
                  className="px-4 py-1.5 rounded-lg bg-[#48F6C1] hover:bg-[#3ce0ad] text-xs font-bold text-[#061219] shadow-sm transition-colors cursor-pointer"
                >
                  Accept
                </button>
              </div>
            </div>

            {/* Custom Cookie Preferences Panel */}
            {showPreferences && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden border-t border-[#1C4659]/40 pt-3 flex flex-col gap-3"
              >
                <div className="flex flex-col gap-2.5">
                  {/* Zoom switch */}
                  <div className="flex items-center justify-between bg-[#061219]/60 p-2 rounded-lg border border-[#1C4659]/40">
                    <div className="flex flex-col max-w-[80%]">
                      <span className="text-xs font-bold text-white">Zoom Layer coordinate persistence</span>
                      <span className="text-[10px] text-[#85A4B1] leading-tight">
                        Saves your last searched coordinate map zoom layer so you avoid re-typing your region during future visits.
                      </span>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={cookieSettings.zoom}
                        onChange={(e) => setCookieSettings({ ...cookieSettings, zoom: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-7 h-4 bg-[#1C4659]/40 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-[#1C4659] after:border after:rounded-full after:height-3 after:width-3 after:transition-all peer-checked:bg-[#48F6C1]"></div>
                    </label>
                  </div>

                  {/* History switch */}
                  <div className="flex items-center justify-between bg-[#061219]/60 p-2 rounded-lg border border-[#1C4659]/40">
                    <div className="flex flex-col max-w-[80%]">
                      <span className="text-xs font-bold text-white">Remember Triage filters</span>
                      <span className="text-[10px] text-[#85A4B1] leading-tight">
                        Remembers your triage history filters to prioritize nearest facilities in subsequent sessions.
                      </span>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={cookieSettings.history}
                        onChange={(e) => setCookieSettings({ ...cookieSettings, history: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-7 h-4 bg-[#1C4659]/40 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-[#1C4659] after:border after:rounded-full after:height-3 after:width-3 after:transition-all peer-checked:bg-[#48F6C1]"></div>
                    </label>
                  </div>

                  {/* Analytics switch */}
                  <div className="flex items-center justify-between bg-[#061219]/60 p-2 rounded-lg border border-[#1C4659]/40">
                    <div className="flex flex-col max-w-[80%]">
                      <span className="text-xs font-bold text-white">Anonymized Transit ETAs</span>
                      <span className="text-[10px] text-[#85A4B1] leading-tight">
                        Improves AI routing suggestions using fully anonymized transit ETAs.
                      </span>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={cookieSettings.analytics}
                        onChange={(e) => setCookieSettings({ ...cookieSettings, analytics: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-7 h-4 bg-[#1C4659]/40 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-[#1C4659] after:border after:rounded-full after:height-3 after:width-3 after:transition-all peer-checked:bg-[#48F6C1]"></div>
                    </label>
                  </div>
                </div>

                <div className="flex items-center justify-between border-t border-[#1C4659]/40 pt-2.5 mt-1">
                  <button 
                    onClick={() => {
                      setCookieSettings({ zoom: false, history: false, analytics: false })
                    }}
                    className="text-[10px] font-bold text-[#FF7B93] hover:text-red-300 transition-colors cursor-pointer"
                  >
                    Reject Optional
                  </button>
                  <button
                    onClick={() => {
                      persistConsent(cookieSettings)
                      setShowPreferences(false)
                      setCookieBannerOpen(false)
                    }}
                    className="px-3.5 py-1 bg-[#1A3F4F] text-white text-[11px] font-bold rounded-md hover:bg-[#204d60] transition-colors cursor-pointer"
                  >
                    Save Preferences
                  </button>
                </div>
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Modern High-End Footer */}
      <footer className="w-full border-t border-[#132A37]/80 bg-[#061219]/50 pt-6 pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))] mt-12">
        <div className="max-w-7xl mx-auto px-6 flex flex-col-reverse md:flex-row items-center justify-between gap-4 text-xs text-[#7AA0B0]">
          <span className="text-center md:text-left">© 2026 MediCoord AI · Patient Routing Platform · Serving Toronto, ON, Canada · Web-based service, no walk-in location. All rights reserved.</span>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Link to="/for-investors" className="hover:text-[#48F6C1] transition-colors">For Investors</Link>
            <Link to="/for-engineers" className="hover:text-[#00D2FF] transition-colors">For Engineers</Link>
            <span className="text-[#1C4659] hidden md:inline" aria-hidden>·</span>
            <Link to="/privacy" className="hover:text-white transition-colors">Privacy Policy</Link>
            <Link to="/cookies" className="hover:text-white transition-colors">Cookie Policy</Link>
            <Link to="/data-disclosure" className="hover:text-white transition-colors">Data Disclosure</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
