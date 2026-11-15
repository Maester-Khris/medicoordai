import { useCallback } from "react"
import { openDirections } from "../lib/directions"

export interface NextActionHandlers {
  call911: () => void
  // Returns false when the facility has no usable coordinates (nothing was opened).
  getDirections: (facilityName: string, lat: number, lng: number) => boolean
}

// LEGAL NOTE: every action here runs only from a user tap or key press.
// The app never dials, messages or opens anything on its own.
// Alert contact and Save are removed until they do something (revisited with the web 911 notification).
export function useNextActions(): NextActionHandlers {
  const call911 = useCallback(() => {
    // Panel and tel: link arrive in the next task (A3).
  }, [])

  const getDirections = useCallback(
    (_facilityName: string, lat: number, lng: number) => openDirections(lat, lng),
    [],
  )

  return { call911, getDirections }
}
