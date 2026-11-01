import type { ReactNode } from 'react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { LoginModal } from '../auth/LoginModal'
import { useDocumentHead } from '../../hooks/useDocumentHead'
import { useAuth } from '../../auth/useAuth'

interface LegalPageLayoutProps {
  title: string
  description: string
  lastUpdated: string
  children: ReactNode
}

export function LegalPageLayout({ title, description, lastUpdated, children }: LegalPageLayoutProps) {
  useDocumentHead(title, description)
  const { isGuest, loading } = useAuth()

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [modalTab, setModalTab] = useState<'signin' | 'signup'>('signin')

  const openSignIn = () => {
    setModalTab('signin')
    setIsModalOpen(true)
  }

  const openSignUp = () => {
    setModalTab('signup')
    setIsModalOpen(true)
  }

  return (
    <div className="min-h-screen bg-[#061219] flex flex-col font-static text-[#E2F1F5] selection:bg-[#48F6C1]/30">
      <LoginModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} defaultTab={modalTab} />

      {/* Modern Navigation Header */}
      <header className="w-full border-b border-[#132A37]/80 bg-[#061219]/90 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-3 min-[360px]:px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-1.5 min-[360px]:gap-3 no-underline">
            <div className="w-8 h-8 min-[360px]:w-9 min-[360px]:h-9 rounded-lg overflow-hidden border border-[#1C4659]/50 flex-none shadow-sm">
              <img src="/logo.png" alt="MediCoord AI Logo" className="w-full h-full object-cover" />
            </div>
            <span className="text-xs min-[360px]:text-label-md font-bold tracking-wide text-white uppercase hidden min-[360px]:inline">
              MediCoord<span className="hidden min-[450px]:inline"> AI</span>
            </span>
          </Link>

          <div className="flex items-center gap-3 min-[360px]:gap-6" style={{ visibility: isGuest || loading ? 'hidden' : 'visible' }}>
            <button onClick={openSignIn} className="text-xs min-[360px]:text-label-md font-medium text-[#7AA0B0] hover:text-[#00D2FF] transition-colors cursor-pointer bg-transparent border-none">
              Sign in
            </button>
            <button
              onClick={openSignUp}
              className="px-2.5 py-1.5 min-[360px]:px-4 min-[360px]:py-2 text-xs min-[360px]:text-label-md font-semibold text-[#061219] rounded-lg bg-[#48F6C1] hover:bg-[#3ce0ad] shadow-sm transition-all duration-250 cursor-pointer active:scale-95 border-none"
            >
              Get started
            </button>
          </div>
        </div>
      </header>

      {/* Main Workspace Layout */}
      <main className="flex-1 max-w-4xl w-full mx-auto px-6 py-12 md:py-16">
        <motion.div
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
        >
          {/* Back link */}
          <Link to="/" className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#7AA0B0] hover:text-[#00D2FF] no-underline transition-colors mb-6">
            ← Back to home
          </Link>

          {/* Premium Glassmorphic Data Card */}
          <div className="bg-[#0A1D27]/80 backdrop-blur-md border border-[#1C4659]/50 rounded-2xl p-6 md:p-10 shadow-2xl">
            <h1 className="text-3xl md:text-4xl font-extrabold text-white tracking-tight mb-2">
              {title}
            </h1>
            <p className="text-xs font-mono text-[#85A4B1] mb-8 border-b border-[#1C4659]/30 pb-4">
              {`Last updated: ${lastUpdated}`}
            </p>

            <div className="text-body-md text-[#85A4B1] space-y-6 [&_a]:text-[#48F6C1] [&_a]:no-underline [&_a:hover]:underline [&_h2]:text-[18px] [&_h2]:font-bold [&_h2]:text-white [&_h2]:tracking-wide [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:border-b [&_h2]:border-[#1C4659]/30 [&_h2]:pb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-2 [&_table]:w-full [&_table]:border-collapse [&_table]:my-6 [&_th]:text-[11px] [&_th]:font-bold [&_th]:font-mono [&_th]:text-[#00D2FF] [&_th]:uppercase [&_th]:tracking-wider [&_th]:text-left [&_th]:border-b [&_th]:border-[#1C4659]/80 [&_th]:py-3 [&_th]:px-4 [&_td]:border-b [&_td]:border-[#1C4659]/40 [&_td]:py-3 [&_td]:px-4 [&_td]:align-top [&_td]:text-[#E2F1F5] [&_tr:hover]:bg-[#132E3C]/20 [&_strong]:text-white">
              {children}
            </div>
          </div>
        </motion.div>
      </main>

      {/* Footer */}
      <footer className="w-full border-t border-[#132A37]/80 bg-[#061219]/50 pt-6 pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))] mt-auto">
        <div className="max-w-7xl mx-auto px-6 flex flex-col-reverse md:flex-row items-center justify-between gap-4 text-xs text-[#7AA0B0]">
          <span className="text-center md:text-left">© 2026 MediCoord AI · Patient Routing Platform. All rights reserved.</span>
          <div className="flex items-center gap-6">
            <Link to="/privacy" className="hover:text-white transition-colors no-underline">Privacy Policy</Link>
            <Link to="/cookies" className="hover:text-white transition-colors no-underline">Cookie Policy</Link>
            <Link to="/data-disclosure" className="hover:text-white transition-colors no-underline">Data Disclosure</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
