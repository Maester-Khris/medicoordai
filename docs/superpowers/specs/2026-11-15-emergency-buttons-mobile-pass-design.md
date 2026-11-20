# Emergency and directions buttons, and the mobile pass: design

Task 016 (Sprint 24, items 4 and 5). Branch `feat/safety-enforcement-and-release`. Status: **approved 2026-11-15 (copy and labels confirmed)**. No application code is written until this spec and the plan are approved.

Inputs: `artifacts/qa/2026-11-15-mobile-audit.md` (findings M-001 to M-028, O-1 to O-5), the owner decisions in the task file ("Settled by the owner", not reopened here), and the code at `6b9bccd`.

## 1. Phase 1 review summary

The audit was produced today against the same commit. I re-read the code behind its top findings and it matches: `useNextActions` is all empty stubs (M-001, M-009); `FacilityCardPanel` has no 911 control and returns `null` without a facility (M-004, M-005); `MobileLayout` mounts `BottomSheet` only in browse mode, so messages and `MedicalNotice` disappear on a result (M-006); `BottomSheet` renders the thread only when expanded and never scrolls it (M-007, M-021); `expandedH` is read once from `window.innerHeight` with `bottom: 64`, which puts the handle under the 56 px top bar (M-008, M-023, M-022); `handleTabChange` resets the conversation for `chat` and `triage` in recommendation mode and does nothing else (M-018). **I did not re-run the browser checks at 320, 360 and 390:** the audit's measurements are from the same commit and the code agrees with them. Phase 5 re-measures everything in Playwright.

**State by platform** (from audit section 3, checked against code):

| Result state | Web 911 | Web directions | Mobile 911 | Mobile directions |
|---|---|---|---|---|
| routine / moderate / urgent | no | button, no-op | no | button, no-op |
| emergent + facility | button, no-op | "ER directions" 34 px, no-op | **missing** | button, no-op |
| emergent, no facility | button, no-op | none | **nothing renders** | none |
| capped (emergent template) | button, no-op | button, no-op | **missing** | button, no-op |
| `triage: null` (capped no-result, no-provider, follow-up, 500, abort) | none | none | none (reply hidden) | none |

**Current e2e:** `playwright.config.ts` has no `projects`, no viewport (default 1280x720), and runs only the live `live-recommendation.spec.ts` (needs backend + Neo4j). The three `*.smoke.spec.ts` files run through `playwright.smoke.config.ts` against a deployed `SMOKE_BASE_URL`, 1280x800, geolocation at Toronto. No phone viewport exists anywhere.

**Ranking.** Blocks use: M-001, M-002, M-003, M-004, M-005, M-006, M-007, M-008, M-009. Degrades use in scope: M-010, M-011, M-013, M-014, M-016, M-018, M-019, M-021, M-022, M-023. Not fixed here: M-012, M-015 (listed for a later accessibility pass; M-015 is only done for the new controls), M-017 (flagged below), M-020, M-024, M-025 (landscape redesign, out of scope; the new sheet model must still work at those sizes), cosmetic M-026 to M-028.

## 2. Decisions

### 2.1 Where Call 911 shows
- **The big red button** renders when `triage.severity === 'emergent'` on both platforms. It reads the structured field, never the reply text. This covers emergent with facility, emergent without facility (M-005) and the capped emergent reply (it carries `severity: emergent`).
- **Replies with no `triage`** (capped no-result, no-provider generic answer, follow-up questions, HTTP and network failures) carry no severity, and the API does not send `cap_reached` to the client (audit section 1). Detecting them by text is forbidden by the task and adding a field is a backend change (out of scope). So the guarantee comes from a second, always-on control: **an "Emergency? Call 911" link in the chat view's header, shown in every state**, independent of any reply. Recommended.
- Web: the same two controls in `ChatPanel`/`TriageCard` (the big button already exists there; the header link is added to the chat header).

### 2.2 What Call 911 does
- **Recommended:** on a touch device (`(pointer: coarse)`), the button is a real `<a href="tel:911">`. A tap opens the phone's dialer with 911 filled in; the user still has to press call, so the app never dials by itself and the legal note holds. On a non-touch device (web) the tap opens an inline panel with the fixed copy below. On touch devices the panel is also shown (the tap handler reveals it, then the browser follows the `tel:` link), so the instructions stay on screen when the user comes back.
- **Why bring `tel:` in although the plan said "later":** a red "Call 911" button on a phone that only prints text is the one control a person in a hurry will tap and expect to dial. The cost is one attribute. **Approved by the owner 2026-11-15 for mobile only.** Web stays template-only for now; a device or web push notification for web is revisited later and is recorded as a note in the Sprint 24 CHANGELOG entry (no separate commit).
- **Copy (safety text, needs owner review):**
  - Button: `Call 911`
  - Panel title: `Call 911 now`
  - Panel body: `Dial 911 on your phone and tell the operator where you are. Stay on the line until they say you can hang up. If someone is with you, ask them to stay with you.`
  - Panel footer: `MediCoord does not place the call or contact anyone for you.`
  - Header link text: `Emergency? Call 911`
  - The copy lives in one constant file `webapp/src/lib/emergency.ts` next to `busy.ts` (`EMERGENCY_LINE` stays there).
- `useNextActions.call911` becomes the state toggle for the panel (open or closed), triggered only by a tap or key press. No side effect on mount, none on render, none from a reply arriving (unit test).
- Panel semantics: `role="alert"` is not used (it is user-initiated, focus moves to the panel title); it has a visible Close button.

### 2.3 Get directions
- `getDirections(name, lat, lng)` builds `https://www.google.com/maps/dir/?api=1&destination=<lat>,<lng>` with `encodeURIComponent` on the joined value, and opens it with `window.open(url, '_blank', 'noopener,noreferrer')`. On a phone the OS hands it to the Maps app; on web it is a new tab.
- If `lat` or `lng` is not a finite number: no navigation, and the button shows an inline message `Directions are not available for this place.` (no throw, no empty tab). Pure function `buildDirectionsUrl(lat, lng): string | null` is unit-tested.
- The web emergent card's "ER directions" grows from 34 px to 44 px and becomes a full-width secondary button below Call 911 (M-010).

### 2.4 Stubs left alone
- `messageEmergencyContact` and `saveRecommendation` stay unimplemented.
- **Approved 2026-11-15.** Both buttons come back together with the later web 911 notification work (noted in the CHANGELOG).
- **Alert contact:** hidden everywhere (remove the `GhostButton`s). Today it only renders when a profile has a phone, which a guest never has; once SMS ships, the button returns with the real handler. A visible button that does nothing is worse than none.
- **Save facility (web) and Save (mobile alternatives):** removed for now. The mobile one is a non-focusable `<span>` and the web one is a no-op (M-014). Acceptance rule: nothing a guest can see is a silent no-op.

### 2.5 Sheet model (O-4, O-5), with the owner's decisions
One `BottomSheet`, always mounted, three states. **The sheet state is the single source of truth; the highlighted tab is derived from it** (no separate `activeTab` state), so tab and sheet cannot drift.

| Tab | Sheet state | Height | Content |
|---|---|---|---|
| Map | `peek` | handle (24) + input row (52) + padding ≈ 96 px | Map visible. Input and Send reachable. If severity is emergent, the red Call 911 strip also stays in peek above the input (44 px). |
| Facilities | `half` | 50 % of the free height, minimum 160 px | Facility list (2.7). |
| Chat | `full` | the free height (below), "about 85 %" in portrait | Thread above, input pinned at the bottom. |

- **Free height** = visual viewport height minus top bar (56) minus nav (64). Sheet height is computed from `window.visualViewport` and updated on `resize`, never read once at mount (M-022). Full state = free height minus 8 px, so the handle is always below the top bar (M-008, M-023). In 667x375 the free height is 255 px: peek 96, half 160, full 247. Still collapsible.
- **Drag:** the handle (a 44 px tall strip, `role="separator"` with `aria-label="Resize chat panel"`, keyboard operable with Arrow Up and Down) snaps to the nearest of the three states by position and velocity. A tap on the handle cycles up one state, from `full` back to `peek`. Dragging and tapping the tabs change the same state.
- **Conversation.** Thread is always rendered in `full` and auto-scrolls to the newest message when one arrives or the sheet opens (M-021). A new reply never needs a drag to be seen (M-007): while the user is on another tab, the Chat tab shows a small dot until opened, and the status line under "AI Health Assistant" is announced with `aria-live="polite"`.
- **Sending from `peek` or `half`:** the sheet rises to `full` on send, so the user sees their message and the answer.
- **Keyboard (visual viewport):** when the on-screen keyboard opens, the sheet goes to `full`, its bottom is lifted by the keyboard height (`innerHeight - visualViewport.height - offsetTop`), the nav is covered by the keyboard and ignored, and the input stays the last element in the sheet, so it is never under the keyboard or the top bar. When the keyboard closes the sheet returns to its previous state.
- **Result arrives** (mode switches to recommendation): the sheet does not unmount. The result is the last block in the thread:
  1. emergent only: full-width red `Call 911` (48 px) at the top of the block;
  2. the assistant reply (this is what keeps the 911 line and "not medical advice" visible, M-006), and `MedicalNotice` stays in the sheet footer in every state;
  3. the facility card (or, with no facility: `We could not find a facility near you. Call 911 or go to the nearest emergency department.`, M-005);
  4. `Get Directions` (non-emergent: primary teal; emergent: secondary, below the card);
  5. travel mode chips, feedback, other nearby options.
  The input stays below for follow-ups. Severity chip in the top bar is unchanged.
- **Non-emergent result:** the sheet stays in `full`. To look at the route the user taps Map (peek) or drags down; the result card has a `Show on map` button that does the same. Emergent: the sheet stays `full` and the Call 911 button is the first thing visible. **Owner chose the recommendation (stay at 85 %).** Was: is leaving the non-emergent result at 85 % acceptable, or should it drop to half on arrival? I recommend leaving it, because it keeps the tab and sheet in sync.
- **Reset:** the cryptic "Clear map" (map overlay and `MobileLayout`) becomes **`New conversation`** (44 px, in the sheet header in the chat view, and as the label of the existing map control). It asks nothing, and is the only action that discards the conversation. Tabs never discard it (fixes M-018).
- **Empty state (no conversation):** starter chips stay under the header in `full` and `peek` shows no chips. Loading: the status line (`SENDING...` or `ANALYZING SYMPTOMS...`) plus a `role="status"` region.

### 2.6 Bottom nav (O-2)
- `MobileTab` becomes `'map' | 'facilities' | 'chat'`; `triage` is deleted from the type, `TABS`, and `handleTabChange`. The grid uses `repeat(${TABS.length}, 1fr)`. Labels go to 12 px (from 9 px) and `Facilities` is shown in sentence case at 12 px to fit 320 px (three columns of 106 px). Each tab is at least 44 px tall (it is 64 now). Tabs are `<button aria-current="page">` for the active one.

### 2.7 Facilities list (O-3), no backend change
- Data: `facilities` already in `MobileLayout` (`useFacilities`). Sort ascending by straight-line distance (haversine in `webapp/src/lib/distance.ts`) from the user's coordinates (`geo.coords`, or the demo downtown fallback from `useConfig`). When the fallback is used, the list header says `Distances from downtown Toronto`.
- Paging: render 8, load 8 more when a sentinel `<li>` enters view (`IntersectionObserver`; no library). Reset the page count when the sort origin changes.
- Row: type icon and colour (hospital red, walk-in teal, residential green, from the existing map legend), name (truncates to one line), distance (`2.4 km`), wait (`~35 min wait`) only when `wait_minutes` is present. Row height ≥ 56 px, a `<button>`.
- Row tap: selects the facility. The row expands inline with `Get Directions` (same function as 2.3) and `Show on map`. `Show on map` switches to `peek` and highlights the marker. **Plan note:** `MapPanel` has no selected-facility prop today, so the plan adds one (`highlightedFacilityId?: string | null`); this is a UI-only change in an existing file.
- Empty state: `No facilities loaded yet.` while loading; `No facilities found.` when the list is empty.
- No "open now" (needs hours parsing and data); listed as a later item.

### 2.8 Guest top bar (O-1)
- When `isGuest`, `MobileTopBar` renders no menu button and `DrawerMenu` is not mounted. Left: the `MediCoordAI` wordmark as plain text (not a button). Right: unchanged (ONLINE pill, or the severity chip). Signed-in users keep the menu, the drawer, and the existing items. Since the demo is guest-only, the drawer is dead code for now and is left untouched.

### 2.9 Failure states (M-002, M-003)
- `useConversations.sendMessage` catches network failures and non-OK responses and returns a typed failure. `MobileLayout` and `ChatPanel` end the pending state and add an assistant-style message: `Something went wrong sending that. Your message was not lost: you can send it again. If this is an emergency, call 911.` The user's text stays in the input for a retry. (This is part of the safety work: the 911 line must show when the app fails.)

### 2.10 Content pass (M-013, M-011, M-010, M-016)
- Remove the invented `[CAPAC] WALK-IN AVAILABILITY: HIGH (EST. WAIT = 30 MIN)` and the hard-coded `OPEN` badge in `FacilityCardPanel` and `TriageCard`. The `[ROUTE]` line is removed with it; `StreamingLogStrip` is no longer rendered in the result.
- Text under 12 px is raised to 12 px for: nav labels, the `MedicalNotice`, the severity chip, the address, the wait-as-of label, and the log-strip removal covers the rest. Others stay (listed for a later pass).
- Primary actions to 44 px: Send, Get Directions, Call 911, feedback thumbs, starter chips, New conversation.
- Location modal: Escape closes it (M-016). Focus trap deferred.

### 2.11 Accessibility floor for changed controls
Visible labels (no icon-only buttons except Send, which keeps `aria-label="Send"`); keyboard operable on web (Tab, Enter, Space, Arrow keys on the handle); at least 44 px touch targets for primary actions; at least 12 px text; `:focus-visible` outline on every new control; the chat status line and the 911 panel are announced (`aria-live`, focus moves to the panel on open).

### 2.12 Contract and severity
- **No contract change.** Uses `severity`, `recommended_facility.lat/lng`, `TriageUIState`. `shared/types.ts` is not edited. The new `MobileTab`, `SheetState` and props are frontend-local.
- **Severity flag (not changed here):** `MobileTopBar` shows `NON-URGENT · ESI 4` for `moderate`, and the web card shows `EMERGENT — ESI 1-2` while mobile shows `ESI 1` (M-017). `NON-URGENT` is not one of the four schema words. **Owner decision 2026-11-15: labels must be uniform on every platform.** Confirmed 2026-11-15: one shared map showing only the schema word, `ROUTINE | MODERATE | URGENT | EMERGENT`, no ESI numbers, used by `MobileTopBar` and `TriageCard`; unit-tested. This is added to the fix list.
- **Safe copy:** nothing diagnoses or promises. The 911 panel gives an instruction, not a medical judgment, and the "not medical advice" line stays in the sheet footer in every state.

## 3. Mobile fix list (blocks use, then degrades use)

| ID | Component | Symptom | Fix | Verified by |
|---|---|---|---|---|
| M-004, M-009 | `FacilityCardPanel`, `TriageCard`, `useNextActions` | no or dead Call 911 | 2.1, 2.2 | unit + e2e emergent, 360 and 1280 |
| M-005 | `MobileLayout`, `FacilityCardPanel` | emergent without facility renders nothing | 2.5 result block | e2e `emergent_nofac` |
| M-006, M-007 | `MobileLayout`, `BottomSheet` | reply and notice hidden | 2.5 | e2e: reply text and notice visible after result |
| M-001 | `useNextActions` | directions no-op | 2.3 | unit URL + e2e popup URL |
| M-002, M-003 | `useConversations`, layouts | failed send is silent | 2.9 | e2e 500 and abort |
| M-008, M-023, M-022 | `BottomSheet` | handle under top bar; wrong height with keyboard | 2.5 free height + visual viewport | e2e 667x375, keyboard emulation |
| M-021 | `BottomSheet` | latest message hidden | auto-scroll | e2e 5 turns |
| M-018, M-019 | `MobileLayout`, `BottomNavBar`, `MobileTopBar` | dead tabs, reset by tab, guest menu | 2.5 to 2.8 | e2e tabs and no menu for guest |
| M-010, M-011, M-013, M-014, M-016 | various | small targets and text, fake data, no-op Save | 2.4, 2.10 | e2e target size, text |

## 4. Out of scope (restated)
Dialing beyond `tel:` (no SMS, no contact alert), landscape redesign, "open now", any backend or contract change, landing page, M-012, M-015 (except new controls), M-017, M-020, M-024 to M-028.

## 5. Open questions for approval
1. `tel:911` link on touch devices (recommended yes, 2.2).
2. 911 copy (2.2) reviewed and approved as written, or edited.
3. Non-emergent result: sheet stays at 85 % (recommended), or drops to half (2.5).
4. M-017 severity labels: leave as is for this task (recommended) and decide separately.
5. Alert contact and Save removed from the UI until they work (recommended, 2.4).
