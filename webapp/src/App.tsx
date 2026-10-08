import * as Sentry from "@sentry/react"
import { useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Home from './Menucomponents/Home'
import SetupPage from './pages/SetupPage'
import TestLocationPage from './pages/TestLocationPage'
import TestNotifPage from './pages/TestNotifPage'
import SandboxPage from './pages/SandboxPage'
import PrivacyPage from './pages/PrivacyPage'
import CookiesPage from './pages/CookiesPage'
import DataDisclosurePage from './pages/DataDisclosurePage'
import LandingPage from './pages/LandingPage'
import ForInvestorsPage from './pages/ForInvestorsPage'
import ForEngineersPage from './pages/ForEngineersPage'
import EngineeringCaseStudyPage from './pages/EngineeringCaseStudyPage'
import ProfilePage from './pages/ProfilePage'
import { OnboardingOverlay } from './components/onboarding/OnboardingOverlay'
import { MobileLayout } from './components/mobile/MobileLayout'
import { AuthProvider } from './auth/AuthContext'
import { Notification } from './components/Notification'
import { GpsPermissionModal } from './components/GpsPermissionModal'
import { PWAInstallModal } from './components/pwa/PWAInstallModal'
import { NotificationPermissionPrompt, shouldShowPermissionPrompt } from './components/pwa/NotificationPermissionPrompt'
import { useFacilities } from './hooks/useFacilities'
import { useConversations } from './hooks/useConversations'
import { useBreakpoint } from './hooks/useBreakpoint'
import { useGeolocation } from './hooks/useGeolocation'
import { usePWAInstall } from './hooks/usePWAInstall'
import { useNotificationPermission } from './hooks/useNotificationPermission'
import { useAuth } from './auth/useAuth'
import { useProfile } from './hooks/useProfile'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isGuest, loading } = useAuth()
  // Until /config and auth resolve we cannot tell a guest from a signed-out visitor;
  // redirecting now would send a guest (or a signed-in user on a deep link) to the landing page.
  if (loading) return null
  // Guests have no account pages: send them to the app instead of the landing page.
  if (isGuest) return <Navigate to="/app" replace />
  if (!user) return <Navigate to="/" replace />
  return <>{children}</>
}

function LandingRoute() {
  return <LandingPage />
}

function AppInner() {
  const isMobile = useBreakpoint()
  const { user, isGuest } = useAuth()
  const { profile, refetch: refetchProfile } = useProfile()
  const { facilities, loading: facilitiesLoading } = useFacilities()
  const { cache, busyUntil, sendMessage, createSession, loadOlderMessages } = useConversations()
  const geo = useGeolocation()
  const [gpsModalDismissed, setGpsModalDismissed] = useState(false)

  const {
    platform,
    installState,
    isPushSupported,
    isIosVersionSupported,
    isIosNonSafari,
    promptInstall,
    installModalDismissed,
    dismissInstallModal,
  } = usePWAInstall()

  const {
    permissionState,
    requesting,
    requestPermission,
  } = useNotificationPermission(isGuest ? null : user?.id ?? null)

  const [permissionPromptDismissed, setPermissionPromptDismissed] = useState(false)
  const [installConfirmed, setInstallConfirmed] = useState(installState === "standalone")

  const showOnboarding = Boolean(!isGuest && user && profile && !profile.getting_started_done)

  const showGpsModal = geo.permission === "denied" && !gpsModalDismissed && !showOnboarding

  const showInstallModal =
    !isGuest &&
    !installModalDismissed &&
    installState !== "standalone" &&
    (platform === "ios_safari" || platform === "android_chrome" || isIosNonSafari) &&
    !installConfirmed &&
    !showOnboarding

  const showPermissionPrompt =
    !isGuest &&
    !showInstallModal &&
    isPushSupported &&
    permissionState !== "granted" &&
    permissionState !== "denied" &&
    !permissionPromptDismissed &&
    shouldShowPermissionPrompt() &&
    !showOnboarding

  const sharedProps = {
    facilities,
    facilitiesLoading,
    conversationsCache: cache,
    sendMessage,
    createSession,
    loadOlderMessages,
    busyUntil,
  }

  if (isMobile && showOnboarding) {
    return <Navigate to="/setup" replace />
  }

  return (
    <>
      <Notification />
      {showGpsModal && (
        <GpsPermissionModal
          onDismiss={() => setGpsModalDismissed(true)}
          dismissLabel={isGuest ? "Continue with downtown Toronto" : undefined}
        />
      )}
      {showInstallModal && (
        <PWAInstallModal
          platform={platform}
          installState={installState}
          isIosVersionSupported={isIosVersionSupported}
          isIosNonSafari={isIosNonSafari}
          promptInstall={promptInstall}
          onInstalled={() => {
            dismissInstallModal()
            setInstallConfirmed(true)
          }}
          onDismiss={dismissInstallModal}
        />
      )}
      {showPermissionPrompt && (
        <NotificationPermissionPrompt
          requesting={requesting}
          onEnable={requestPermission}
          onDismiss={() => setPermissionPromptDismissed(true)}
        />
      )}
      {!isMobile && showOnboarding && <OnboardingOverlay onComplete={refetchProfile} />}
      {isMobile
        ? <MobileLayout {...sharedProps} />
        : <Home {...sharedProps} />
      }
    </>
  )
}

function App() {
  return (
    <Sentry.ErrorBoundary
      fallback={({ error }) => (
        <div style={{ padding: 24 }}>
          <p>Something went wrong. Please refresh.</p>
          {import.meta.env.DEV && <pre>{String(error)}</pre>}
        </div>
      )}
    >
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingRoute />} />
            <Route path="/app" element={<AppInner />} />
            <Route path="/setup" element={<ProtectedRoute><SetupPage /></ProtectedRoute>} />
            <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
            <Route path="/testlocation" element={<TestLocationPage />} />
            <Route path="/sandbox" element={<ProtectedRoute><SandboxPage /></ProtectedRoute>} />
            <Route path="/test-notif" element={<TestNotifPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            <Route path="/cookies" element={<CookiesPage />} />
            <Route path="/data-disclosure" element={<DataDisclosurePage />} />
            <Route path="/for-investors" element={<ForInvestorsPage />} />
            <Route path="/for-engineers" element={<ForEngineersPage />} />
            <Route path="/for-engineers/:slug" element={<EngineeringCaseStudyPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </Sentry.ErrorBoundary>
  )
}

export default App
