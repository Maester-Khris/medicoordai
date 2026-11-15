// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import { EmergencyCall } from "./EmergencyCall"
import { EMERGENCY_COPY } from "../lib/emergency"

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root | null = null
let host: HTMLDivElement | null = null

function mount(touch: boolean, variant: "primary" | "link" = "primary"): HTMLDivElement {
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
  act(() => root!.render(<EmergencyCall touch={touch} variant={variant} />))
  return host
}

afterEach(() => {
  act(() => root?.unmount())
  host?.remove()
  root = null
  host = null
})

describe("EmergencyCall", () => {
  it("shows nothing but the trigger until it is tapped", () => {
    const el = mount(false)
    expect(el.textContent).toBe(EMERGENCY_COPY.button)
    expect(el.querySelector("[data-testid=emergency-panel]")).toBeNull()
  })

  it("on web opens the template panel with the approved copy and no link", () => {
    const el = mount(false)
    const trigger = el.querySelector("button")!
    expect(el.querySelector("a")).toBeNull()
    act(() => trigger.click())
    const panel = el.querySelector("[data-testid=emergency-panel]")!
    expect(panel.textContent).toContain(EMERGENCY_COPY.title)
    expect(panel.textContent).toContain(EMERGENCY_COPY.body)
    expect(panel.textContent).toContain(EMERGENCY_COPY.footer)
    expect(document.activeElement).toBe(panel.querySelector("[data-testid=emergency-title]"))
  })

  it("on a touch device the trigger is a tel:911 link and also reveals the panel", () => {
    const el = mount(true)
    const link = el.querySelector("a")!
    expect(link.getAttribute("href")).toBe("tel:911")
    link.addEventListener("click", e => e.preventDefault()) // jsdom cannot navigate
    act(() => link.click())
    expect(el.querySelector("[data-testid=emergency-panel]")).not.toBeNull()
  })

  it("closes with the Close button", () => {
    const el = mount(false)
    act(() => el.querySelector("button")!.click())
    act(() => (el.querySelector("[data-testid=emergency-close]") as HTMLButtonElement).click())
    expect(el.querySelector("[data-testid=emergency-panel]")).toBeNull()
  })

  it("the link variant uses the header wording", () => {
    expect(mount(false, "link").textContent).toBe(EMERGENCY_COPY.headerLink)
  })
})
