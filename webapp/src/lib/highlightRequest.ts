// A "show this facility on the map" request. The counter makes picking the same facility twice
// a new request, so the map flies there again.
export interface HighlightRequest {
  id: string
  requestId: number
}

export function nextHighlightRequest(previous: HighlightRequest | null, id: string): HighlightRequest {
  return { id, requestId: (previous?.requestId ?? 0) + 1 }
}
