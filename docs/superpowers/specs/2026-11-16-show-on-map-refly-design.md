# "Show on map" flies again on every tap: design (short)

Follow-up to task 016 (known issue). Branch `feat/safety-enforcement-and-release`. Status: **draft, awaiting approval**. Size: small change, short design.

## Intent
In the mobile facilities list, "Show on map" flies the map to the facility and rings it. Today it only works the first time for a given facility: re-picking it later does nothing. A tap must always fly the map there, because the user may have panned away since. The user wants the ring to be a short "look here" cue, not a permanent mark.

## Cause (read from the code)
`MobileLayout` keeps `highlightedFacilityId`. `MapPanel` turns the id into a facility object with `useMemo([facilities, id])` and passes it to `HighlightedFacility`, whose fly-to effect depends on that object. Same id gives the same object, so the effect does not re-run. A reload of `/facilities` gives a new object, so the map would also fly with no tap. The ring has no end and survives "New conversation".

## Goals
- Every "Show on map" tap flies the map to that facility and shows the ring, even for the same facility.
- A facilities reload never moves the map.
- The ring fades by itself a few seconds after the map arrives, and is cleared by "New conversation".
- No extra re-render of `MapPanel` for the fade (it rebuilds every marker icon; see the 660-to-0 fix in `7c6c1c1`).

## Non-goals and anti-goals
- No change to markers, popups or the triage route drawing.
- No imperative or event channel that bypasses React; not worth the code unless measurement shows one `MapPanel` render per tap is a problem.
- Anti-goal: the cue must not vanish before the user can see it (the sheet drop and the fly take about 1.1 s).

## Approaches considered
1. **Ring stays** until another pick or "New conversation". Simplest, but stale and cluttered after panning.
2. **Ring fades after a few seconds** (chosen by the user). Replays on each tap. Timer lives inside the ring component.
3. **Ring clears when the user drags the map.** Precise, but an accidental touch removes the cue, and it does nothing for users who never touch the map.
Choice: 2, with the counter below. Reason: best cue-to-clutter ratio at the lowest cost.

## Design (my calls, for review)
- **Request, not id.** `MobileLayout` stores `highlightRequest: { id: string; requestId: number } | null`. `handleShowOnMap(id)` sets `{ id, requestId: previous + 1 }`; `handleNewConversation` sets `null`. A small pure function `nextHighlightRequest(previous, id)` holds the counter rule (unit tested).
- **Prop.** `MapPanel` takes `highlightRequest` instead of `highlightedFacilityId`. It resolves the facility by id (`useMemo` on `facilities` and `request.id`) and passes both to `HighlightedFacility`.
- **Effect keyed on the request only.** In `HighlightedFacility`, the fly-to effect depends on `request` (not on the facility object); the coordinates are read from a ref, so a data reload cannot trigger it. A missing facility is a no-op.
- **Fly and fade.** Fly to `max(current zoom, 15)` over 0.8 s. With `prefers-reduced-motion` use `setView` without animation. The ring is shown at once. A 4 s timer (constant `RING_VISIBLE_MS`) starts on the map's `moveend`, with a 1.2 s fallback if no `moveend` fires (the map was already there), and hides the ring. A new request cancels the old timer and shows the ring again. The timer and its visible flag are local state inside `HighlightedFacility`, so the fade does not re-render `MapPanel`. Cleanup on unmount.
- **Skills used as lenses:** pragmatic-programmer (orthogonality: the cue's lifetime is local to the ring component), clean-code (named constant, small effect, no magic numbers), clean-architecture (map details stay inside the map component; the layout only sends a request).

## Verification (what the plan will test first)
- Unit: `nextHighlightRequest` increments, and gives a new request for the same id.
- End-to-end (phone-360, stubbed backend): pick a facility, the ring appears; wait for it to fade; pan the map away; pick the same facility again, the ring reappears centred in the map container. A `/facilities` reload (re-sent response) does not move the map or show the ring.
- Existing checks stay green: marker-pane mutations per keystroke still 0; full vitest and the 70 Playwright tests.

## Left to the builder
Exact timer and `moveend` wiring, how to simulate a pan in Playwright, and the reduced-motion check.
