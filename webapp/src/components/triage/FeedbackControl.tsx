import { useState } from "react"
import type { FeedbackRequest, Thumb } from "@shared/types"
import { apiFetch } from "../../lib/apiClient"

interface FeedbackControlProps {
  sessionId: string
  messageId: string
}

type SaveState = "idle" | "saving" | "saved" | "error"

const BUTTON_STYLE: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: 8,
  fontSize: 13,
  cursor: "pointer",
  background: "rgba(10, 29, 39, 0.6)",
  color: "#E2F1F5",
}

export function FeedbackControl({ sessionId, messageId }: FeedbackControlProps) {
  const [thumb, setThumb] = useState<Thumb | null>(null)
  const [comment, setComment] = useState("")
  const [state, setState] = useState<SaveState>("idle")

  const send = async (nextThumb: Thumb, nextComment: string) => {
    setThumb(nextThumb)
    setState("saving")
    const body: FeedbackRequest = {
      session_id: sessionId,
      message_id: messageId,
      thumb: nextThumb,
      comment: nextComment.trim() || null,
    }
    try {
      const res = await apiFetch("/feedback", { method: "POST", body: JSON.stringify(body) })
      setState(res.ok ? "saved" : "error")
    } catch {
      setState("error")
    }
  }

  const border = (value: Thumb) =>
    `1px solid ${thumb === value ? "rgba(72,246,193,0.7)" : "rgba(28,70,89,0.6)"}`

  return (
    <div data-testid="feedback-control" className="mt-2 flex flex-col gap-2" style={{ fontFamily: "var(--font-sans)" }}>
      <div className="flex items-center gap-2">
        <span className="text-[11px]" style={{ color: "#7AA0B0" }}>Was this helpful?</span>
        <button type="button" aria-label="Helpful" aria-pressed={thumb === "up"} data-testid="feedback-up"
          onClick={() => { void send("up", "") }} style={{ ...BUTTON_STYLE, border: border("up") }}>
          👍
        </button>
        <button type="button" aria-label="Not helpful" aria-pressed={thumb === "down"} data-testid="feedback-down"
          onClick={() => { void send("down", comment) }} style={{ ...BUTTON_STYLE, border: border("down") }}>
          👎
        </button>
        {state === "saved" && <span data-testid="feedback-saved" className="text-[11px]" style={{ color: "#48F6C1" }}>Thanks</span>}
        {state === "error" && <span className="text-[11px]" style={{ color: "#F59E0B" }}>Could not save. Try again.</span>}
      </div>

      {thumb === "down" && (
        <div className="flex gap-2">
          <input
            aria-label="What went wrong? (optional)"
            placeholder="What went wrong? (optional)"
            value={comment}
            maxLength={2000}
            onChange={e => setComment(e.target.value)}
            className="flex-1 text-[12px] rounded-lg px-2 py-1.5 focus:outline-none"
            style={{ background: "rgba(10,29,39,0.6)", border: "1px solid rgba(28,70,89,0.6)", color: "#E2F1F5" }}
          />
          <button type="button" disabled={state === "saving"} onClick={() => { void send("down", comment) }}
            style={{ ...BUTTON_STYLE, border: "1px solid rgba(28,70,89,0.6)" }}>
            Send
          </button>
        </div>
      )}
    </div>
  )
}
