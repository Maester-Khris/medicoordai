# Architecture — MediCoord AI

## System Overview

MediCoord AI is a two-surface application: a React frontend and a Python backend. In Phase 1, the only user-facing flow is the symptom chat → AI triage → map routing loop. All other surfaces (auth, database, analytics) are deferred.

---

## Surfaces and Responsibilities

### Frontend — Vercel
**Stack:** React 18, Vite, TypeScript (strict), Tailwind CSS, React Leaflet

Responsibilities:
- Render the split chat + map home page
- Capture user symptom input and stream it to the backend
- Display tool-call progress trace during AI processing ("Analyzing symptoms… Locating facilities… Calculating route…")
- Render the Claude/Groq response in the chat panel
- On triage result: place user pin on map, draw route polyline, highlight destination facility
- Request browser geolocation with explicit user consent prompt

Does NOT:
- Make direct calls to Geoapify, Groq, or Anthropic — all AI/routing calls go through the backend
- Store any patient data client-side beyond the current session

### Backend — Railway (Web Service)
**Stack:** Python 3.11, FastAPI, Pydantic

Responsibilities:
- Expose the `/triage` endpoint (see `docs/API.md`)
- Orchestrate the parallel + chained LLM tool workflow
- Abstract the LLM provider behind a single client (`backend/llm/client.py`) switchable via `LLM_PROVIDER` flag
- Call Geoapify Route Matrix API server-side
- Return structured triage results to the frontend

Does NOT:
- Persist data to a database (Phase 1)
- Handle authentication (Phase 1)
- Serve the frontend

### Background Worker — Railway (Cron / Worker Service)
Implemented for ER wait-time scraping as a Railway cron service (`workers/railway.toml`, every 15 min).

---

## Data Flow — Phase 1 Triage Loop

```
User types symptoms
        │
        ▼
Frontend POST /triage { message, lat, lng }
        │
        ▼
Backend: parallel tool dispatch
        ├── Tool 1a: LLM client (Groq or Anthropic)
        │           → structured output: severity + reasoning
        └── Tool 1b: lat/lng already in request payload
        │
        ▼
Backend: chained tool dispatch
        └── Tool 2: Geoapify RouteMatrix
                    sources: [{ lat, lng }] (user)
                    targets: all facilities filtered by severity
                    → travel times + distances
                    → select nearest appropriate facility
        │
        ▼
Backend: compose response
        └── TriageResult { severity, facilityId, travelMinutes, reasoning, routeCoords }
        │
        ▼
Frontend: render
        ├── Chat panel: LLM explanation + recommendation
        └── Map panel: user pin + polyline + facility highlight
```

---

## LLM Provider Abstraction

The backend uses a single client interface regardless of provider:

```
backend/
└── llm/
    ├── client.py       # Abstract interface — get_llm_client() → LLMClient
    ├── groq.py         # Groq implementation (default)
    └── anthropic.py    # Anthropic implementation
```

Provider is selected at startup via `LLM_PROVIDER` env var (`groq` | `anthropic`). No provider-specific code should appear outside of `backend/llm/`.

---

## Deployment Topology

```
                    Vercel
                ┌──────────────┐
User browser ──▶│  React SPA   │
                └──────┬───────┘
                       │ POST /triage
                       ▼
                    Railway
                ┌──────────────┐
                │  FastAPI app │──▶ Groq API
                │              │──▶ Anthropic API
                │              │──▶ Geoapify API
                └──────────────┘
```

Environment variables are managed in Doppler and injected at runtime. The frontend (Vercel) reads `VITE_*` values at build time; the backend (Railway) reads them at runtime. Doppler configs: `dev`, `dev_personal`, `stg`, `prd`, `eval`.

---

## Toronto Facility Dataset

`shared/facilities.ts` (or `backend/data/facilities.json`) — 43 Toronto health providers with:
- `id`, `name`, `lat`, `lng`
- `type`: `hospital | clinic | urgent_care | walk_in`
- `acceptedSeverity`: array of severity levels this facility handles

The `acceptedSeverity` field drives facility filtering in Tool 2: an `emergent` patient is only routed to `hospital` type facilities.

---

## Shared Types

All API contract types live in `shared/types.ts`. Both the frontend (TypeScript import) and backend (Pydantic models mirroring the same schema) must stay in sync with this file. See `docs/API.md` for the full contract.

---

## Phase 2 (Deferred)
- Supabase: session persistence, user accounts, patient history
- Supabase Auth: JWT-based auth for the frontend, verified on the backend
- Emergency contact notification (user-initiated, not autonomous)
- Predictive analytics tab