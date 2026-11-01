const GUEST_KEY = "mc_guest_id"
const INTERNAL_KEY = "mc_internal"
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// Used only when localStorage is blocked (private mode, strict settings): the id then lasts for the page.
let memoryGuestId: string | null = null

export function getGuestId(): string {
  try {
    const stored = localStorage.getItem(GUEST_KEY)
    if (stored && UUID_RE.test(stored)) return stored
    const fresh = crypto.randomUUID()
    localStorage.setItem(GUEST_KEY, fresh)
    return fresh
  } catch {
    memoryGuestId ??= crypto.randomUUID()
    return memoryGuestId
  }
}

/** `?internal=<token>` marks this browser as an internal tester from then on. */
export function captureInternalToken(search: string): void {
  const token = new URLSearchParams(search).get("internal")
  if (!token) return
  try {
    localStorage.setItem(INTERNAL_KEY, token)
  } catch {
    // storage blocked: this browser simply is not marked
  }
}

export function getInternalToken(): string | null {
  try {
    return localStorage.getItem(INTERNAL_KEY)
  } catch {
    return null
  }
}
