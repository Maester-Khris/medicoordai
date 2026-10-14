import { useState, useEffect, useRef } from "react"
import type { Facility } from "../../../shared/types"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

interface UseFacilitiesResult {
  facilities: Facility[]
  loading: boolean
  error: string | null
  /** ISO time of the worker's last successful run, from the X-Wait-As-Of header. */
  waitAsOf: string | null
}

export function useFacilities(): UseFacilitiesResult {
  const [facilities, setFacilities] = useState<Facility[]>([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState<string | null>(null)
  const [waitAsOf, setWaitAsOf]     = useState<string | null>(null)
  const etagRef                     = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function fetchFacilities() {
      try {
        const headers: Record<string, string> = {}
        if (etagRef.current) {
          headers["If-None-Match"] = etagRef.current
        }

        const res = await fetch(`${BASE_URL}/facilities`, { headers })

        if (res.status === 304) {
          setLoading(false)
          return
        }

        if (!res.ok) {
          throw new Error(`Failed to load facilities (${res.status})`)
        }

        const etag = res.headers.get("ETag")
        if (etag) etagRef.current = etag

        const data: Facility[] = await res.json() as Facility[]
        if (!cancelled) {
          setFacilities(data)
          setWaitAsOf(res.headers.get("X-Wait-As-Of"))
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unknown error")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void fetchFacilities()
    return () => { cancelled = true }
  }, [])

  return { facilities, loading, error, waitAsOf }
}
