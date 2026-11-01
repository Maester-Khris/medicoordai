import { useState, useRef, useCallback, useEffect } from "react"

export interface Coords {
  lat: number
  lng: number
}

export interface GeoError {
  code: number
  message: string
}

export type GeolocationPermission = "granted" | "denied" | "prompt" | "unsupported"

interface UseGeolocationResult {
  coords: Coords | null
  requesting: boolean
  denied: boolean
  lastError: GeoError | null
  permission: GeolocationPermission
  requestOnce: () => Promise<Coords | null>
  setCoords: (coords: Coords | null) => void
}

export function useGeolocation(): UseGeolocationResult {
  const [coords, setCoords] = useState<Coords | null>(null)
  const [requesting, setRequesting] = useState(false)
  const [denied, setDenied] = useState(false)
  const [lastError, setLastError] = useState<GeoError | null>(null)
  const [permission, setPermission] = useState<GeolocationPermission>("prompt")
  const resolvedRef = useRef(false)

  // Silent probe: timeout:0 + maximumAge:Infinity returns a cached fix instantly
  // or errors immediately — no GPS wake-up on desktop.
  // On iOS, PERMISSION_DENIED is incorrectly reported as TIMEOUT when timeout:0
  // and no cached position exists (spec violation). The TIMEOUT fallback below
  // issues a real request so denial is surfaced correctly on iOS.
  const probeGeolocationSilently = useCallback(() => {
    navigator.geolocation.getCurrentPosition(
      pos => {
        const c = { lat: pos.coords.latitude, lng: pos.coords.longitude }
        setCoords(c)
        setPermission("granted")
        resolvedRef.current = true
      },
      err => {
        if (err.code === err.PERMISSION_DENIED) {
          setPermission("denied")
          setDenied(true)
        } else if (err.code === err.TIMEOUT) {
          // iOS masks PERMISSION_DENIED as TIMEOUT when no cached position exists.
          // Re-probe with a real timeout to surface the actual denial state.
          navigator.geolocation.getCurrentPosition(
            pos => {
              const c = { lat: pos.coords.latitude, lng: pos.coords.longitude }
              setCoords(c)
              setPermission("granted")
              resolvedRef.current = true
            },
            err2 => {
              if (err2.code === err2.PERMISSION_DENIED) {
                setPermission("denied")
                setDenied(true)
              }
              // TIMEOUT / POSITION_UNAVAILABLE → leave as "prompt"
            },
            { enableHighAccuracy: false, timeout: 5000, maximumAge: Infinity }
          )
        }
        // POSITION_UNAVAILABLE → treat as "prompt", leave state unchanged
      },
      { maximumAge: Infinity, timeout: 0 }
    )
  }, [])

  // On mount: use permissions API where available (Android Chrome, desktop).
  // iOS (Safari and Chrome) is excluded: even when permissions.query resolves,
  // it returns "prompt" regardless of the real state, so the probe is used instead.
  useEffect(() => {
    if (!navigator.geolocation) {
      setPermission("unsupported")
      return
    }

    const isIOS =
      /iphone|ipad|ipod/i.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)

    if (!isIOS && navigator.permissions) {
      navigator.permissions
        .query({ name: "geolocation" })
        .then(result => {
          setPermission(result.state as GeolocationPermission)
          if (result.state === "denied") setDenied(true)

          result.onchange = () => {
            setPermission(result.state as GeolocationPermission)
            setDenied(result.state === "denied")
            if (result.state === "granted") resolvedRef.current = false
          }
        })
        .catch(() => {
          probeGeolocationSilently()
        })
    } else {
      probeGeolocationSilently()
    }
  }, [probeGeolocationSilently])

  // iOS has no onchange listener — re-probe when the user returns to the tab
  // after potentially changing location settings.
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && permission === "denied") {
        probeGeolocationSilently()
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange)
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange)
  }, [permission, probeGeolocationSilently])

  const requestOnce = useCallback((): Promise<Coords | null> => {
    if (resolvedRef.current && coords) return Promise.resolve(coords)
    if (!navigator.geolocation) return Promise.resolve(null)

    setRequesting(true)
    return new Promise(resolve => {
      navigator.geolocation.getCurrentPosition(
        pos => {
          const c = { lat: pos.coords.latitude, lng: pos.coords.longitude }
          setCoords(c)
          setDenied(false)
          setLastError(null)
          setPermission("granted")
          resolvedRef.current = true
          setRequesting(false)
          resolve(c)
        },
        err => {
          const geo: GeoError = { code: err.code, message: err.message }
          console.error("Geolocation error:", geo)
          setLastError(geo)
          if (err.code === err.PERMISSION_DENIED) {
            setDenied(true)
            setPermission("denied")
          }
          setRequesting(false)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ;(window as any).lastGeoError = err
          resolve(null)
        },
        { enableHighAccuracy: false, timeout: 20000, maximumAge: 120000 }
      )
    })
  }, [coords])

  return { coords, requesting, denied, lastError, permission, requestOnce, setCoords }
}
