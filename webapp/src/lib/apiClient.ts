import * as Sentry from "@sentry/react"
import { authService } from "../auth/authService"

import { getConfig } from "./config"
import { getGuestId, getInternalToken } from "./guest"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

export async function apiFetch(path: string, options: RequestInit = {}) {
  const config = await getConfig()

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> ?? {}),
  }

  if (config.demo_mode) {
    headers["X-Guest-Id"] = getGuestId()
    const internalToken = getInternalToken()
    if (internalToken) headers["X-Internal"] = internalToken
  } else {
    const token = await authService.getAccessToken()
    if (token) headers["Authorization"] = `Bearer ${token}`
  }

  const activeSpan = Sentry.getActiveSpan()
  headers["X-Request-ID"] = activeSpan
    ? Sentry.spanToTraceHeader(activeSpan)
    : crypto.randomUUID()

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers })

  if (res.status === 401) {
    throw new Error("Unauthorized")
  }

  return res
}
