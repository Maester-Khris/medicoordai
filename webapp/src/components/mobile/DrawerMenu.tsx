import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/useAuth'
import { formatDisplayName } from '../../lib/formatDisplayName'

interface DrawerMenuProps {
  isOpen: boolean
  onClose: () => void
}

function HomeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1H5a1 1 0 01-1-1V9.5z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M9 21V12h6v9"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ProfileIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="7" r="4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}


function ChevronRightIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function SignOutIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <polyline
        points="16,17 21,12 16,7"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <line
        x1="21"
        y1="12"
        x2="9"
        y2="12"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function DrawerMenu({ isOpen, onClose }: DrawerMenuProps) {
  const { user, signOut, isGuest } = useAuth()
  const navigate = useNavigate()

  const email = user?.email ?? ''
  const initials = isGuest ? 'G' : email ? email[0].toUpperCase() : '?'
  const displayName = isGuest ? 'Guest' : email ? formatDisplayName(email) : ''

  const handleHome = () => {
    onClose()
    navigate('/')
  }

  const handleProfile = () => {
    onClose()
    navigate('/profile')
  }

  const handleSignOut = async () => {
    onClose()
    await signOut()
  }

  return (
    <>
      {/* Overlay */}
      <div
        aria-hidden="true"
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 40,
          background: 'rgba(0,0,0,0.4)',
          opacity: isOpen ? 1 : 0,
          pointerEvents: isOpen ? 'auto' : 'none',
          transition: 'opacity 0.2s ease',
        }}
      />

      {/* Drawer */}
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          zIndex: 50,
          width: 260,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          transform: isOpen ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform 0.25s ease',
          background: 'rgba(10, 29, 39, 0.95)',
          backdropFilter: 'blur(16px)',
          borderRight: '1px solid rgba(28, 70, 89, 0.40)',
        }}
      >
        {/* User info */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '40px 20px 20px' }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: '50%',
              background: '#35A7C4',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#061219',
              fontSize: 18,
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {initials}
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: 14, fontWeight: 600, color: '#E2F1F5', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-sans)' }}>
              {displayName}
            </p>
            <p style={{ fontSize: 12, color: '#85A4B1', margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-sans)' }}>
              {email}
            </p>
          </div>
        </div>

        <div style={{ height: 1, background: 'rgba(28, 70, 89, 0.40)', margin: '0 20px' }} />

        {/* Home */}
        <button
          onClick={handleHome}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '0 20px',
            minHeight: 44,
            width: '100%',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
            color: '#E2F1F5',
            fontFamily: 'var(--font-sans)',
          }}
        >
          <HomeIcon />
          <span style={{ flex: 1, fontSize: 14 }}>Home</span>
          <span style={{ color: '#85A4B1' }}>
            <ChevronRightIcon />
          </span>
        </button>

        <div style={{ height: 1, background: 'rgba(28, 70, 89, 0.40)', margin: '0 20px' }} />

        {/* My profile */}
        {!isGuest && (
          <button
            onClick={handleProfile}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '0 20px',
              minHeight: 44,
              width: '100%',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              textAlign: 'left',
              color: '#E2F1F5',
              fontFamily: 'var(--font-sans)',
            }}
          >
            <ProfileIcon />
            <span style={{ flex: 1, fontSize: 14 }}>My profile</span>
            <span style={{ color: '#85A4B1' }}>
              <ChevronRightIcon />
            </span>
          </button>
        )}



        {/* Sign out */}
        {!isGuest && (
          <button
            onClick={handleSignOut}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '0 20px',
              minHeight: 44,
              width: '100%',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              textAlign: 'left',
              color: '#FF7B93',
              fontFamily: 'var(--font-sans)',
            }}
          >
            <SignOutIcon />
            <span style={{ flex: 1, fontSize: 14 }}>Sign out</span>
          </button>
        )}
      </div>
    </>
  )
}
