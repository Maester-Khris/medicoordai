import { useCallback } from "react"
import type { Severity } from "../../../shared/types"

export interface NextActionHandlers {
  call911: () => void
  messageEmergencyContact: (contactPhone: string | null) => void
  getDirections: (facilityName: string, lat: number, lng: number) => void
  saveRecommendation: () => void
}

export function useNextActions(severity: Severity | null): NextActionHandlers {
  const call911 = useCallback(() => {
    // LEGAL NOTE: This action is always user-initiated via a tap/click.
    // The app never dials autonomously. This opens the native phone dialer only.
    // TODO (separate task): implement tel:911 deep link
  }, [severity])

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const messageEmergencyContact = useCallback((_contactPhone: string | null) => {
    // LEGAL NOTE: This opens the native SMS composer pre-filled with a template.
    // No server-side message sending. User must tap Send in their SMS app.
    // TODO (separate task): implement sms: deep link with pre-filled body
  }, [])

  const getDirections = useCallback((
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    _facilityName: string,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    _lat: number,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    _lng: number,
  ) => {
    // TODO (separate task): open Google Maps deep link
    // https://www.google.com/maps/dir/?api=1&destination={lat},{lng}
  }, [])

  const saveRecommendation = useCallback(() => {
    // TODO (separate task): persist recommendation to user profile or clipboard
  }, [severity])

  return { call911, messageEmergencyContact, getDirections, saveRecommendation }
}
