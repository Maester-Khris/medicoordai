import { createContext, useState, useEffect, useCallback } from "react"
import type { ReactNode } from "react"
import { supabase } from "../lib/supabaseClient"
import { authService } from "./authService"

import { getConfig } from "../lib/config"
import { captureInternalToken, getGuestId } from "../lib/guest"

interface AuthUser {
  id: string
  email: string | undefined
}

export interface AuthNotification {
  type: "error" | "success"
  text: string
}

export interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  isGuest: boolean
  notification: AuthNotification | null
  clearNotification: () => void
  signInWithEmail: (email: string, password: string) => Promise<void>
  signUpWithEmail: (email: string, password: string) => Promise<void>
  signInWithGoogle: () => Promise<void>
  signOut: () => Promise<void>
}

function toFriendlyError(err: { message: string; status?: number }): string {
  const msg = err.message.toLowerCase()
  if (err.status === 429 || msg.includes("rate limit")) {
    return "Too many attempts. Please wait a few minutes before trying again."
  }
  if (msg.includes("invalid login credentials")) {
    return "Incorrect email or password."
  }
  if (msg.includes("email not confirmed")) {
    return "Please confirm your email before signing in."
  }
  if (msg.includes("user already registered")) {
    return "An account with this email already exists. Try signing in instead."
  }
  return err.message
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [isGuest, setIsGuest] = useState(false)
  const [notification, setNotification] = useState<AuthNotification | null>(null)

  const clearNotification = useCallback(() => setNotification(null), [])

  useEffect(() => {
    let cancelled = false
    let unsubscribe = () => {}

    void getConfig().then(config => {
      if (cancelled) return

      if (config.demo_mode) {
        // Guest demo: the browser's random id stands in for the signed-in user everywhere.
        captureInternalToken(window.location.search)
        setUser({ id: getGuestId(), email: undefined })
        setIsGuest(true)
        setLoading(false)
        return
      }

      supabase.auth.getSession().then(({ data }) => {
        if (cancelled) return
        const session = data.session
        setUser(session?.user ? { id: session.user.id, email: session.user.email } : null)
        setLoading(false)
      })

      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        setUser(session?.user ? { id: session.user.id, email: session.user.email } : null)
      })
      unsubscribe = () => subscription.unsubscribe()
    })

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [])

  const signInWithEmail = async (email: string, password: string) => {
    setLoading(true)
    setNotification(null)
    const { error: err } = await authService.signInWithEmail(email, password)
    if (err) setNotification({ type: "error", text: toFriendlyError(err) })
    setLoading(false)
  }

  const signUpWithEmail = async (email: string, password: string) => {
    setLoading(true)
    setNotification(null)
    const { error: err } = await authService.signUpWithEmail(email, password)
    if (err) {
      setNotification({ type: "error", text: toFriendlyError(err) })
    } else {
      setNotification({ type: "success", text: "Account created! Check your inbox to confirm your email." })
    }
    setLoading(false)
  }

  const signInWithGoogle = async () => {
    setNotification(null)
    await authService.signInWithGoogle()
  }

  const signOut = async () => {
    if (isGuest) return
    setNotification(null)
    await authService.signOut()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{
      user, loading, isGuest, notification, clearNotification,
      signInWithEmail, signUpWithEmail, signInWithGoogle, signOut
    }}>
      {children}
    </AuthContext.Provider>
  )
}

