import { useCallback } from "react"
import { openDirections } from "../lib/directions"

export interface NextActionHandlers {
  // Returns false when the facility has no usable coordinates (nothing was opened).
  getDirections: (facilityName: string, lat: number, lng: number) => boolean
}

// LEGAL NOTE: every action here runs only from a user tap or key press.
// The app never dials, messages or opens anything on its own. Call 911 lives in EmergencyCall.
// Alert contact and Save are removed until they do something (revisited with the web 911 notification).
export function useNextActions(): NextActionHandlers {
  const getDirections = useCallback(
    (_facilityName: string, lat: number, lng: number) => openDirections(lat, lng),
    [],
  )

  return { getDirections }
}
