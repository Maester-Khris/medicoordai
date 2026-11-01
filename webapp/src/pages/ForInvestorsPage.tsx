import { useState, useEffect, Fragment } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowRight, ShieldCheck, ChartBar, Globe, Flask, PlayIcon, PauseIcon } from '@phosphor-icons/react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { useDocumentHead } from '../hooks/useDocumentHead'
import { useConfig } from '../hooks/useConfig'

interface PipelineStep {
  id: string
  label: string
  icon: string
  color: string
  techWhat: string
  bizWhy: string
  metric: { label: string; value: string }
  detail: string
}

const PIPELINE_STEPS: PipelineStep[] = [
  {
    id: 'intake',
    label: 'Patient Intake',
    icon: 'ti ti-message-chatbot',
    color: '#48F6C1',
    techWhat: 'Lay-language symptoms + geolocation ingested via secure API.',
    bizWhy: 'No phone calls. No intake forms. Patients enter the coordination queue instantly — staff time goes to care, not routing.',
    metric: { label: 'Ingestion latency', value: '18 ms' },
    detail: 'Validates and sanitizes patient payloads, extracts coordinates via browser or mobile SDK, and pushes to the triage queue. Handles 42 concurrent requests per minute per node without degradation.'
  },
  {
    id: 'triage',
    label: 'AI Triage',
    icon: 'ti ti-brain',
    color: '#00D2FF',
    techWhat: 'Multi-agent LLM grounded on a 12,400-node ICD-10-CA Knowledge Graph classifies severity.',
    bizWhy: 'Emergent cases never route to urgent care. Clinical capability is gated before ETA is considered — preventing dangerous misroutes.',
    metric: { label: 'Reasoning time', value: '120 ms' },
    detail: 'Reasoning is constrained to verified KG pathways. The model cannot return a severity tag without a matching graph path — eliminating the hallucination failure mode that makes bare LLM triage unsafe for clinical use.'
  },
  {
    id: 'load',
    label: 'Load Check',
    icon: 'ti ti-device-sd-card',
    color: '#F59E0B',
    techWhat: 'Redis reads live queue levels and in-flight patient counts atomically.',
    bizWhy: 'Prevents flooding the current "best" facility — which recreates the bottleneck the system was built to solve. Load self-distributes.',
    metric: { label: 'Cache read latency', value: '< 0.8 ms' },
    detail: 'Maintains an atomic in-flight buffer: patients routed but not yet admitted. Every scoring decision reads this count first, so 2,500 concurrent updates remain consistent without blocking writes.'
  },
  {
    id: 'route',
    label: 'Route Calc',
    icon: 'ti ti-compass',
    color: '#A855F7',
    techWhat: 'OSRM computes road geometry and a composite ETA: travel time plus current queue wait.',
    bizWhy: 'A clinic 1.5 km away with a 60-min queue loses to a hospital 4 km away with a 23-min total ETA. Distance alone misleads.',
    metric: { label: 'Route latency', value: '< 2 ms' },
    detail: 'Polylines computed for car, cycling, and transit modes. Composite score is never computed for an ineligible facility type — severity gates capability before distance is evaluated.'
  },
  {
    id: 'dispatch',
    label: 'Facility Match',
    icon: 'ti ti-map-pin-check',
    color: '#48F6C1',
    techWhat: 'Optimal facility selected; dispatch written to Redis, incrementing the in-flight count.',
    bizWhy: 'Future routing decisions for concurrent patients factor this count in — the system never optimizes locally at the expense of system-wide throughput.',
    metric: { label: 'Full pipeline', value: '< 300 ms' },
    detail: 'The dispatch closes an atomic loop. The same infrastructure that read the in-flight count now increments it — ensuring every parallel routing decision operates on current state, not a stale snapshot.'
  }
]

const LIVE_STATS = [
  { label: 'Pipeline Time', value: '< 300 ms', color: '#48F6C1' },
  { label: 'Facilities Tracked', value: '34', color: '#00D2FF' },
  { label: 'Active Bottlenecks', value: '0', color: '#A855F7' },
  { label: 'Concurrent Patients', value: '247', color: '#F59E0B' },
] as const

function PatientFlowPipeline() {
  const [activeStep, setActiveStep] = useState(0)
  const [isPlaying, setIsPlaying] = useState(true)
  const shouldReduceMotion = useReducedMotion()

  useEffect(() => {
    if (!isPlaying) return
    const interval = setInterval(() => {
      setActiveStep(prev => (prev + 1) % PIPELINE_STEPS.length)
    }, 2800)
    return () => clearInterval(interval)
  }, [isPlaying])

  const step = PIPELINE_STEPS[activeStep]

  return (
    <div className="flex flex-col gap-6 w-full border border-[#132A37]/80 bg-[#0A1D27]/40 rounded-2xl p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <motion.span
            className="w-2 h-2 rounded-full bg-[#48F6C1] flex-none"
            animate={shouldReduceMotion ? {} : { opacity: [1, 0.3, 1] }}
            transition={{ repeat: Infinity, duration: 2, ease: 'easeInOut' }}
          />
          <span className="text-xs font-mono font-bold text-[#48F6C1] uppercase tracking-wider">
            Live Patient Routing Pipeline
          </span>
        </div>
        <button
          onClick={() => setIsPlaying(p => !p)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[#1C4659]/60 bg-[#061219]/80 text-xs font-mono text-[#7AA0B0] hover:text-white hover:border-[#48F6C1]/40 transition-colors duration-150"
        >
          {isPlaying
            ? <PauseIcon weight="fill" className="w-3 h-3" />
            : <PlayIcon weight="fill" className="w-3 h-3" />}
          {isPlaying ? 'Pause' : 'Play'}
        </button>
      </div>

      {/* Pipeline nodes + connectors */}
      <div className="flex items-start w-full px-1">
        {PIPELINE_STEPS.map((s, i) => {
          const isActive = i === activeStep
          const isComplete = i < activeStep

          return (
            <Fragment key={s.id}>
              {/* Node */}
              <button
                onClick={() => { setActiveStep(i); setIsPlaying(false) }}
                className="flex flex-col items-center gap-2 flex-none focus:outline-none group"
                style={{ width: 64 }}
              >
                <div className="relative flex items-center justify-center">
                  <motion.div
                    className="w-11 h-11 rounded-full flex items-center justify-center border relative z-10"
                    animate={{
                      borderColor: isActive ? s.color : isComplete ? s.color + '70' : '#1C4659',
                      backgroundColor: isActive
                        ? s.color + '1A'
                        : isComplete
                          ? s.color + '0D'
                          : 'rgba(6,18,25,0.8)',
                      boxShadow: isActive ? `0 0 18px ${s.color}33` : 'none',
                    }}
                    transition={{ duration: 0.25, ease: 'easeOut' }}
                  >
                    <i
                      className={`${s.icon} text-base`}
                      style={{
                        color: isActive ? s.color : isComplete ? s.color + 'AA' : '#3A6070',
                        transition: 'color 0.25s ease',
                      }}
                    />
                  </motion.div>

                  {/* Pulse ring — active node only */}
                  {isActive && !shouldReduceMotion && (
                    <motion.div
                      className="absolute inset-0 rounded-full border"
                      style={{ borderColor: s.color }}
                      animate={{ scale: [1, 1.6], opacity: [0.5, 0] }}
                      transition={{ repeat: Infinity, duration: 1.4, ease: 'easeOut' }}
                    />
                  )}
                </div>

                <span
                  className="text-[9px] font-mono text-center leading-tight hidden sm:block"
                  style={{
                    color: isActive ? '#E2F1F5' : isComplete ? '#5A7F90' : '#2E5060',
                    transition: 'color 0.25s ease',
                  }}
                >
                  {s.label}
                </span>
              </button>

              {/* Connector */}
              {i < PIPELINE_STEPS.length - 1 && (
                <div className="flex-1 h-0.5 mt-5 mx-0.5 relative overflow-hidden rounded-full">
                  {/* Base track */}
                  <div
                    className="absolute inset-0 rounded-full transition-colors duration-300"
                    style={{
                      background: i < activeStep
                        ? PIPELINE_STEPS[i].color + '55'
                        : '#1C4659',
                    }}
                  />
                  {/* Active sweep */}
                  {i === activeStep && !shouldReduceMotion && (
                    <motion.div
                      className="absolute inset-0 rounded-full"
                      style={{
                        background: `linear-gradient(to right, transparent 0%, ${s.color}CC 50%, transparent 100%)`,
                      }}
                      animate={{ x: ['-100%', '100%'] }}
                      transition={{ repeat: Infinity, duration: 0.85, ease: 'linear' }}
                    />
                  )}
                  {/* Reduced-motion active */}
                  {i === activeStep && shouldReduceMotion && (
                    <div className="absolute inset-0 rounded-full" style={{ background: s.color + '80' }} />
                  )}
                </div>
              )}
            </Fragment>
          )
        })}
      </div>

      {/* Detail panel */}
      <AnimatePresence mode="wait">
        <motion.div
          key={step.id}
          initial={shouldReduceMotion ? { opacity: 0 } : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={shouldReduceMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
          className="grid grid-cols-1 lg:grid-cols-3 gap-5 border border-[#1C4659]/40 bg-[#061219]/60 rounded-xl p-5"
        >
          {/* Left: step identity + what/why */}
          <div className="lg:col-span-2 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center flex-none"
                style={{
                  background: step.color + '15',
                  border: `1px solid ${step.color}30`,
                  color: step.color,
                }}
              >
                <i className={`${step.icon} text-xl`} />
              </div>
              <div>
                <div
                  className="text-[9px] font-mono uppercase tracking-wider"
                  style={{ color: step.color }}
                >
                  {`Step ${activeStep + 1} of ${PIPELINE_STEPS.length}`}
                </div>
                <div className="text-sm font-bold text-white">{step.label}</div>
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <div>
                <div className="text-[9px] font-mono text-[#7AA0B0] uppercase tracking-wider mb-1.5">What happens</div>
                <p className="text-xs text-[#A8C8D8] leading-relaxed">{step.techWhat}</p>
              </div>
              <div className="border-t border-[#1C4659]/30 pt-3">
                <div
                  className="text-[9px] font-mono uppercase tracking-wider mb-1.5"
                  style={{ color: step.color }}
                >
                  Why it matters
                </div>
                <p className="text-sm font-medium text-white leading-relaxed">{step.bizWhy}</p>
              </div>
            </div>
          </div>

          {/* Right: metric + detail */}
          <div className="flex flex-col gap-4 border-t border-[#1C4659]/30 pt-4 lg:border-t-0 lg:pt-0 lg:border-l lg:border-[#1C4659]/30 lg:pl-5">
            <div>
              <div className="text-[9px] font-mono text-[#7AA0B0] uppercase tracking-wider mb-1">{step.metric.label}</div>
              <div className="text-3xl font-mono font-bold leading-none" style={{ color: step.color }}>
                {step.metric.value}
              </div>
            </div>
            <div className="border-t border-[#1C4659]/20 pt-3">
              <div className="text-[9px] font-mono text-[#7AA0B0] uppercase tracking-wider mb-1.5">Technical detail</div>
              <p className="text-[11px] text-[#6A8A9A] leading-relaxed">{step.detail}</p>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>

      {/* Live stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {LIVE_STATS.map(stat => (
          <div
            key={stat.label}
            className="border border-[#1C4659]/40 bg-[#061219]/40 rounded-xl p-3 flex flex-col gap-1"
          >
            <span className="text-[9px] font-mono text-[#7AA0B0] uppercase tracking-wider">{stat.label}</span>
            <span className="text-xl font-mono font-bold" style={{ color: stat.color }}>
              {stat.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ForInvestorsPage() {
  const config = useConfig()
  useDocumentHead(
    'For Investors & Health System Operators',
    "City-wide patient coordination, real-time and at scale. How MediCoord AI routes hundreds of patients simultaneously across Toronto's health network."
  )

  return (
    <div className="bg-[#061219] min-h-screen flex flex-col font-static text-[#E2F1F5] overflow-x-hidden">

      {/* Header */}
      <header className="w-full border-b border-[#132A37]/80 bg-[#061219]/90 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg overflow-hidden border border-[#1C4659]/50 flex-none shadow-sm">
              <img src="/logo.png" alt="MediCoord AI" className="w-full h-full object-cover" />
            </div>
            <span className="text-xs font-bold tracking-wide text-white uppercase">MediCoord AI</span>
          </div>
          <Link to="/" className="flex items-center gap-1.5 text-xs text-[#7AA0B0] hover:text-white transition-colors">
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to overview
          </Link>
        </div>
      </header>

      <main className="flex-1 max-w-7xl mx-auto px-6 py-16 lg:py-24 w-full flex flex-col gap-16">

        {/* Hero */}
        <div className="flex flex-col gap-5 max-w-3xl">
          <div className="inline-flex items-center self-start gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-[#48F6C1]/10 text-[#48F6C1] border border-[#48F6C1]/20 tracking-wider uppercase">
            For Health System Operators & Investors
          </div>
          <h1 className="text-4xl lg:text-5xl font-extrabold text-white leading-tight tracking-tight">
            City-wide patient coordination.<br />Real-time. At scale.
          </h1>
          <p className="text-[#85A4B1] text-base leading-relaxed max-w-2xl">
            MediCoord AI routes hundreds of patients simultaneously across Toronto's health network — prioritized by severity, balanced by load, in real time.
          </p>
        </div>

        {/* Three callout cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="border border-[#1C4659]/50 bg-[#0A1D27]/80 rounded-2xl p-7 flex flex-col gap-4">
            <div className="w-11 h-11 rounded-xl bg-[#48F6C1]/10 border border-[#48F6C1]/20 text-[#48F6C1] flex items-center justify-center">
              <ChartBar className="w-5 h-5" />
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="text-lg font-bold text-white">Priority Queue</h3>
              <p className="text-sm text-[#85A4B1] leading-relaxed">
                Severity-weighted dispatch. Emergent cases route first. Moderate and routine cases absorb available city-wide capacity without crowding critical pathways.
              </p>
            </div>
          </div>

          <div className="border border-[#1C4659]/50 bg-[#0A1D27]/80 rounded-2xl p-7 flex flex-col gap-4">
            <div className="w-11 h-11 rounded-xl bg-[#00D2FF]/10 border border-[#00D2FF]/20 text-[#00D2FF] flex items-center justify-center">
              <Globe className="w-5 h-5" />
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="text-lg font-bold text-white">City-Wide Coordination</h3>
              <p className="text-sm text-[#85A4B1] leading-relaxed">
                All facilities tracked simultaneously. Load redistributes as patient volume shifts across the network. No single facility becomes a new bottleneck.
              </p>
            </div>
          </div>

          <div className="border border-[#1C4659]/50 bg-[#0A1D27]/80 rounded-2xl p-7 flex flex-col gap-4">
            <div className="w-11 h-11 rounded-xl bg-[#48F6C1]/10 border border-[#48F6C1]/20 text-[#48F6C1] flex items-center justify-center">
              <Flask className="w-5 h-5" />
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="text-lg font-bold text-white">Org Sandbox</h3>
              <p className="text-sm text-[#85A4B1] leading-relaxed">
                Evaluate with simulated patient load. No PHI, no live infrastructure, full coordination fidelity. Watch routing and rebalancing before any commitment.
              </p>
            </div>
          </div>
        </div>

        {/* Interactive Pipeline */}
        <section className="flex flex-col gap-6">
          <div className="flex flex-col gap-2">
            <h2 className="text-2xl lg:text-3xl font-extrabold text-white">How a routing decision happens</h2>
            <p className="text-sm text-[#85A4B1] max-w-xl leading-relaxed">
              From patient symptom to facility confirmation in under 300 ms. Click any stage to inspect it, or watch the pipeline run.
            </p>
          </div>
          <PatientFlowPipeline />
        </section>

        {/* Main pitch */}
        <section className="border-t border-[#132A37]/80 pt-16 flex flex-col gap-8 max-w-3xl">
          <h2 className="text-2xl lg:text-3xl font-extrabold text-white leading-snug">
            {'Most routing systems find the nearest facility. '}
            <span className="text-[#48F6C1]">MediCoord AI coordinates across all of them.</span>
          </h2>
          <div className="flex flex-col gap-5 text-[#85A4B1] text-sm leading-relaxed">
            <p>
              The system scores every candidate facility by composite ETA: road travel time plus active wait queue — not proximity. A clinic 1.5 km away with a 60-minute queue loses to a hospital 4 km away with a 23-minute total ETA. Severity gates minimum facility capability: emergent cases never route to urgent care regardless of ETA advantage.
            </p>
            <p>
              As facilities fill, routing decisions shift to preserve system-wide throughput. Inbound routing decisions in flight are factored into each new score — preventing the coordination trap of sending every patient to the same "best" option and recreating the bottleneck you set out to solve.
            </p>
          </div>
        </section>

        {/* Sandbox CTA */}
        <div className="border border-[#00D2FF]/30 bg-[#0A1D27]/80 rounded-2xl p-8 flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="flex flex-col gap-2">
            <span className="text-xs font-mono font-bold text-[#00D2FF] uppercase tracking-wider">
              Available for Organizations — Sandbox Mode
            </span>
            <h3 className="text-xl font-bold text-white">See the coordination in action</h3>
            <p className="text-sm text-[#85A4B1] max-w-xl leading-relaxed">
              Run a simulated patient load across the city network. Watch priority queue dispatch and load rebalancing in real time. No PHI, no live infrastructure required.
            </p>
          </div>
          {!config.demo_mode && (
          <Link
            to="/sandbox"
            className="flex-none inline-flex items-center gap-2 px-6 py-3 text-sm font-bold text-[#061219] bg-[#00D2FF] hover:bg-[#00b4db] rounded-xl shadow-sm transition-all duration-200 active:scale-95 whitespace-nowrap"
          >
            Launch Sandbox Mode
            <ArrowRight className="w-4 h-4" />
          </Link>
          )}
        </div>

        {/* Trust row */}
        <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-[#132A37]/80 pt-8 text-xs font-mono text-[#7AA0B0]">
          {[
            'Built on real Canadian public health data',
            'Toronto facility network',
            'Session-only, zero PHI storage',
          ].map((item) => (
            <div key={item} className="flex items-center gap-2">
              <ShieldCheck className="w-3.5 h-3.5 text-[#48F6C1] flex-none" />
              <span>{item}</span>
            </div>
          ))}
        </div>

      </main>

      {/* Footer */}
      <footer className="w-full border-t border-[#132A37]/80 bg-[#061219]/50 py-6 mt-8">
        <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-[#7AA0B0]">
          <span>© 2026 MediCoord AI · Patient Routing Platform. All rights reserved.</span>
          <Link to="/" className="hover:text-white transition-colors">← Back to overview</Link>
        </div>
      </footer>

    </div>
  )
}
