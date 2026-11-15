import { useEffect, useRef, useState } from "react"
import { EMERGENCY_COPY } from "../lib/emergency"

interface EmergencyCallProps {
  variant: "primary" | "link"
  // Injected for tests; defaults to the device's pointer type.
  touch?: boolean
  // Called when the panel opens (the sheet uses it to make room).
  onOpen?: () => void
}

function isTouchDevice(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches === true
}

const PRIMARY_STYLE = {
  minHeight: 48,
  background: "#FF7B93",
  color: "#061219",
  border: "none",
  borderRadius: 10,
  fontSize: 15,
  fontWeight: 700,
  cursor: "pointer",
  textDecoration: "none",
} as const

const LINK_STYLE = {
  minHeight: 44,
  background: "none",
  border: "none",
  color: "#FF7B93",
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "underline",
  cursor: "pointer",
} as const

// LEGAL: runs only from a tap or key press. On touch devices the link opens the dialer;
// the user still has to press call. On web it shows the template panel only.
export function EmergencyCall({ variant, touch, onOpen }: EmergencyCallProps) {
  const [open, setOpen] = useState(false)
  const titleRef = useRef<HTMLParagraphElement>(null)
  const isTouch = touch ?? isTouchDevice()
  const label = variant === "primary" ? EMERGENCY_COPY.button : EMERGENCY_COPY.headerLink
  const style = variant === "primary" ? PRIMARY_STYLE : LINK_STYLE
  const className = "flex items-center justify-center w-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"

  const reveal = () => { setOpen(true); onOpen?.() }

  useEffect(() => {
    if (open) titleRef.current?.focus()
  }, [open])

  return (
    <div className="flex flex-col gap-2">
      {isTouch ? (
        <a href="tel:911" onClick={reveal} className={className} style={style}>{label}</a>
      ) : (
        <button type="button" onClick={reveal} className={className} style={style}>{label}</button>
      )}
      {open && (
        <div
          data-testid="emergency-panel"
          className="rounded-lg p-3"
          style={{ background: "rgba(255,123,147,0.10)", border: "1px solid rgba(255,123,147,0.45)", color: "#E2F1F5" }}
        >
          <p ref={titleRef} tabIndex={-1} data-testid="emergency-title" className="font-bold text-[15px]">
            {EMERGENCY_COPY.title}
          </p>
          <p className="text-[13px] mt-1 leading-relaxed">{EMERGENCY_COPY.body}</p>
          <p className="text-[12px] mt-2" style={{ color: "#85A4B1" }}>{EMERGENCY_COPY.footer}</p>
          <button
            type="button"
            data-testid="emergency-close"
            onClick={() => setOpen(false)}
            className="mt-2 text-[13px] font-semibold underline"
            style={{ minHeight: 44, background: "none", border: "none", color: "#E2F1F5", cursor: "pointer" }}
          >
            Close
          </button>
        </div>
      )}
    </div>
  )
}
