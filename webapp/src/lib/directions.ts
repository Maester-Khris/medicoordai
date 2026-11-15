export const DIRECTIONS_UNAVAILABLE = "Directions are not available for this place."

export function buildDirectionsUrl(lat: number, lng: number): string | null {
  const valid =
    Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180
  if (!valid) return null
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(`${lat},${lng}`)}`
}

type OpenFn = (url: string, target: string, features: string) => unknown

// Always called from a user tap. Returns false when the facility has no usable coordinates.
export function openDirections(lat: number, lng: number, open: OpenFn = window.open.bind(window)): boolean {
  const url = buildDirectionsUrl(lat, lng)
  if (!url) return false
  open(url, "_blank", "noopener,noreferrer")
  return true
}
