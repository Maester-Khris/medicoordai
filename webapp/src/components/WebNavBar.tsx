import { Link } from 'react-router-dom'
import { useConfig } from '../hooks/useConfig'

interface WebNavBarProps {
  rightContent?: React.ReactNode
}

export function WebNavBar({ rightContent }: WebNavBarProps) {
  const config = useConfig()
  return (
    <header
      className="flex-none flex items-center justify-between px-8 z-10 sticky top-0"
      style={{
        height: 64,
        background: 'rgba(6, 18, 25, 0.92)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(19, 42, 55, 0.80)',
      }}
    >
      <Link to="/app" className="flex items-center gap-3 no-underline">
        <div
          className="flex items-center justify-center w-9 h-9 rounded-lg flex-none overflow-hidden shadow-md"
          style={{ border: '1px solid rgba(28, 70, 89, 0.5)' }}
        >
          <img src="/logo.png" alt="MediCoord AI" className="w-full h-full object-cover" />
        </div>
        <div className="leading-tight flex flex-col">
          <span
            className="text-label-md font-bold tracking-wide uppercase"
            style={{ color: '#E2F1F5' }}
          >
            MediCoord<span style={{ color: '#48F6C1' }}>AI</span>
          </span>
          <span
            className="text-mono-meta uppercase tracking-widest"
            style={{ color: '#7AA0B0', fontSize: 9 }}
          >
            Health Coordination
          </span>
        </div>
      </Link>

      <div className="flex items-center gap-4 ml-auto">
        {!config.demo_mode && (
        <Link
          to="/sandbox"
          className="flex items-center gap-1.5 no-underline transition-all active:scale-95 hover:scale-102"
          style={{
            padding: '6px 14px',
            fontSize: 11,
            fontWeight: 700,
            color: '#061219',
            background: '#F59E0B',
            borderRadius: 8,
            boxShadow: '0 0 12px rgba(245, 158, 11, 0.3)',
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLElement).style.background = '#d97706'
            ;(e.currentTarget as HTMLElement).style.boxShadow = '0 0 16px rgba(245, 158, 11, 0.5)'
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLElement).style.background = '#F59E0B'
            ;(e.currentTarget as HTMLElement).style.boxShadow = '0 0 12px rgba(245, 158, 11, 0.3)'
          }}
        >
          <i className="ti ti-test-pipe" style={{ fontSize: 13 }} />
          Sandbox
        </Link>
        )}
        {rightContent && <div className="flex items-center gap-4">{rightContent}</div>}
      </div>
    </header>
  )
}
