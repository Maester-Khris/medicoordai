// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"

vi.mock("../auth/useAuth", () => ({ useAuth: () => ({ user: null }) }))
const apiFetch = vi.fn()
vi.mock("../lib/apiClient", () => ({ apiFetch: (...a: unknown[]) => apiFetch(...a) }))

import { useConversations, type ChatMessageResponse, type Session } from "./useConversations"

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Api = ReturnType<typeof useConversations>
let api: Api
let root: Root
let host: HTMLDivElement

function Probe() {
  api = useConversations()
  return null
}

beforeEach(() => {
  apiFetch.mockReset()
  host = document.createElement("div")
  root = createRoot(host)
  act(() => root.render(<Probe />))
})
afterEach(() => act(() => root.unmount()))

describe("sendMessage failures", () => {
  it("returns 'failed' instead of throwing on a network error", async () => {
    apiFetch.mockRejectedValue(new TypeError("Failed to fetch"))
    let result: ChatMessageResponse | "busy" | "failed" | undefined
    await act(async () => { result = await api.sendMessage("s", "hi") })
    expect(result).toBe("failed")
  })

  it("returns 'failed' on a 500", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 500 })
    let result: ChatMessageResponse | "busy" | "failed" | undefined
    await act(async () => { result = await api.sendMessage("s", "hi") })
    expect(result).toBe("failed")
  })

  it("returns 'busy' on a long 429 wait", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 429, json: async () => ({ retry_after: 120 }) })
    let result: ChatMessageResponse | "busy" | "failed" | undefined
    await act(async () => { result = await api.sendMessage("s", "hi") })
    expect(result).toBe("busy")
  })
})

describe("createSession failures", () => {
  it("returns null instead of throwing on a network error", async () => {
    apiFetch.mockRejectedValue(new TypeError("Failed to fetch"))
    let result: Session | null | undefined
    await act(async () => { result = await api.createSession("hi") })
    expect(result).toBeNull()
  })
})
