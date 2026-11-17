# "Show on map" re-fly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (small, two tasks, one session). Steps use checkbox syntax.

**Goal:** every "Show on map" tap flies the map to the facility and shows a ring that fades by itself; a facilities reload never moves the map.

**Architecture:** the layout sends a request `{ id, requestId }` (counter) instead of an id. The ring component keys its fly-to effect on the request, owns the fade timer locally, so `MapPanel` re-renders once per tap and not for the fade.

**Tech Stack:** React 18, react-leaflet, vitest, Playwright (`playwright.mobile.config.ts`).

**Spec:** `docs/superpowers/specs/2026-11-16-show-on-map-refly-design.md`

## Global Constraints
- TypeScript strict, no `any`, no new npm package, no backend or `shared/types.ts` change.
- `RING_VISIBLE_MS = 4000` after `moveend`; fallback `1200` ms if no `moveend`; fly to `Math.max(map.getZoom(), 15)` over `0.8` s; reduced motion: `map.setView` without animation.
- The marker-pane mutation count per keystroke must stay 0 (`MapPanel` stays memoised).
- **One commit for the whole fix**, including the spec and this plan (user rule, 2026-11-16). Conventional one-line message, no AI trailer, never push.

## Review Focus
- Same facility tapped twice after panning away: map flies again and ring reappears (task 2 end-to-end).
- Tap, then "New conversation": ring is gone (task 2, request set to `null`).
- Facility id not in the list: nothing happens, no error (task 2, covered by the `facility === null` branch; no test, Leaflet cannot be mounted in jsdom here).
- `/facilities` reload while a ring is showing: map does not move (by construction: the effect depends on `request` only; not tested, the stub cannot re-send mid-test without extra plumbing).
- Two quick taps on different facilities: the first timer must not hide the second ring (task 2, timer is cleared on each request).

---

### Task 1: the request type and counter

**Files:**
- Create: `webapp/src/lib/highlightRequest.ts`
- Test: `webapp/src/lib/highlightRequest.test.ts`

**Interfaces:**
- Produces: `interface HighlightRequest { id: string; requestId: number }` and `function nextHighlightRequest(previous: HighlightRequest | null, id: string): HighlightRequest`.

- [ ] **Step 1: Write the failing test** `highlightRequest.test.ts` with: `first request starts at 1`; `the same id again gets a new requestId` (expect `next.id === prev.id` and `next.requestId === prev.requestId + 1`); `a different id also increments`.
- [ ] **Step 2: Run** `doppler run -- npx vitest run src/lib/highlightRequest.test.ts` from `webapp/`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement** `nextHighlightRequest` returning `{ id, requestId: (previous?.requestId ?? 0) + 1 }`.
- [ ] **Step 4: Run** the same command. Expected: 3 passed.

### Task 2: wire the layout and the map, fade the ring

**Files:**
- Modify: `webapp/src/components/mobile/MobileLayout.tsx` (state at the `highlightedFacilityId` line, `handleShowOnMap`, `handleNewConversation`, the `MapPanel` prop)
- Modify: `webapp/src/components/map/MapPanel.tsx` (prop `highlightedFacilityId` becomes `highlightRequest?: HighlightRequest | null`; the `highlighted` memo; `HighlightedFacility`)
- Test: `webapp/e2e/phone.mobile.spec.ts` (new test, `phone-360` and the other phone projects)

**Interfaces:**
- Consumes: `HighlightRequest`, `nextHighlightRequest` from Task 1.
- Produces: `MapPanel` prop `highlightRequest?: HighlightRequest | null`; `HighlightedFacility({ request, facility }: { request: HighlightRequest | null; facility: { lat: number; lng: number } | null })`.

- [ ] **Step 1: Write the failing end-to-end test** in `phone.mobile.spec.ts`: `show on map twice: the ring appears, fades, and reappears after panning away`. Open `routine`, tap Facilities, expand the first row, tap `facility-show-on-map`; expect `.leaflet-overlay-pane path` visible; expect it hidden within 10 s (fade); drag the map away with `page.mouse` (about 120 px); repeat the row expand and "Show on map" on the same row; expect the ring visible again and its bounding-box centre within 40 px of the centre of `.leaflet-container`.
- [ ] **Step 2: Run** `PLAYWRIGHT_CHROMIUM_EXECUTABLE=<cached headless shell> npx playwright test -c playwright.mobile.config.ts --project=phone-360 -g "show on map twice"`. Expected: FAIL on the second ring (never reappears).
- [ ] **Step 3: `MobileLayout`:** state `highlightRequest: HighlightRequest | null`; `handleShowOnMap` sets `prev => nextHighlightRequest(prev, facilityId)` then `setSheetState('peek')`; `handleNewConversation` also sets it to `null`; pass `highlightRequest` to `MapPanel`.
- [ ] **Step 4: `MapPanel` and `HighlightedFacility`:** resolve `facility` with `useMemo` on `facilities` and `highlightRequest?.id`; pass both to `HighlightedFacility`. Inside it: keep the facility in a ref; one effect keyed on `request` only that (a) returns if `request` or the facility is null, (b) cancels the previous timer, shows the ring (`useState`), (c) flies (or `setView` under `prefers-reduced-motion`), (d) starts the hide timer on the first `moveend` (`map.once`) or after the 1200 ms fallback, whichever is first, with cleanup that cancels the timer and the listener. Name the constants `RING_VISIBLE_MS`, `MOVEEND_FALLBACK_MS`. Render the `CircleMarker` only while shown.
- [ ] **Step 5: Run** the Step 2 command. Expected: PASS. Then rerun the whole phone suite (`--project=phone-360`, then all projects): expected all pass.
- [ ] **Step 6: Check performance did not regress:** run `node /tmp/claude-1000/c/churn.mjs` (keystroke churn script). Expected: `0` mutations for 10 keystrokes. Run `npx tsc -b`, `npx eslint` on the touched files, and the full `doppler run -- npx vitest run`. Expected: clean.
- [ ] **Step 7: Commit once** (one commit for the fix, spec and plan included):
  `git add docs/superpowers/specs/2026-11-16-show-on-map-refly-design.md docs/superpowers/plans/2026-11-16-show-on-map-refly.md webapp/src/lib/highlightRequest.ts webapp/src/lib/highlightRequest.test.ts webapp/src/components/mobile/MobileLayout.tsx webapp/src/components/map/MapPanel.tsx webapp/e2e/phone.mobile.spec.ts`
  `git commit -m "fix(frontend): fly to the facility on every show on map tap and fade the ring"`
- [ ] **Step 8: Tracking:** the known issue was only in the task 016 summary, not in the CHANGELOG, so no CHANGELOG edit is needed; mention the fix in the final summary.
