import { useState, useEffect } from "react"
import { supabase } from "../lib/supabaseClient"
import { useAuth } from "../auth/useAuth"
import type { Profile } from "@shared/types"

export type { Profile }

export function useProfile() {
  const { user, isGuest } = useAuth()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(false)

  const refetch = async () => {
    if (!user || isGuest) { setProfile(null); return }
    setLoading(true)
    const { data } = await supabase
      .from('profile')
      .select('*')
      .eq('user_id', user.id)
      .single()
    setProfile(data)
    setLoading(false)
  }

  useEffect(() => {
    refetch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, isGuest])

  const updateProfile = async (updates: Partial<Profile>) => {
    if (!user || isGuest) return
    const { data, error } = await supabase
      .from('profile')
      .update(updates)
      .eq('user_id', user.id)
      .select()
      .single()
    if (error) throw new Error(error.message)
    setProfile(data)
  }

  return { profile, loading, updateProfile, refetch }
}
