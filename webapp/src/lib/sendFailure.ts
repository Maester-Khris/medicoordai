import type { Message } from "@shared/types"
import { SEND_FAILED_MESSAGE } from "./busy"

// A local assistant-style note shown when a send fails; never stored on the server.
export function failureMessage(sessionId: string, userId: string): Message {
  return {
    id: crypto.randomUUID(),
    session_id: sessionId,
    user_id: userId,
    role: "assistant",
    content: SEND_FAILED_MESSAGE,
    created_at: new Date().toISOString(),
  }
}
