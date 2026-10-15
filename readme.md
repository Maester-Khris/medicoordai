# MediCoord AI

**AI-powered city-wide health coordination system**  
Toronto Tech Week 2025 Hackathon → SaaS rebuild in progress

---

## What This Is

MediCoord AI is a health coordination platform designed to reduce the friction between a patient experiencing symptoms and the right care provider reaching them in time.

A user describes how they feel in natural language. The system classifies their symptom severity, locates them, identifies the most appropriate nearby facility, and routes them there — all surfaced in a single conversational interface backed by a live city map.

The system is designed for city-scale deployment: any Toronto resident with a browser can open it, describe their symptoms, and receive a real routing recommendation without needing to know which hospital handles what, how far away anything is, or what their condition actually warrants.

---

## Background

This project was originally built for **Toronto Tech Week 2025** as a hackathon submission under a 48-hour constraint. The goal was to demonstrate AI-driven triage and coordination at a city scale using Toronto's actual healthcare facility layout.

The hackathon build shipped a working frontend simulation — a React map interface that generates synthetic patients, routes them to providers using the Geoapify Route Matrix API, and visualizes queue state per hospital. It also included a GCP Cloud Function with Gemini 2.5 Flash for symptom extraction and a fine-tuned Vertex AI classifier for severity prediction.

**What worked at submission:** the frontend simulation, the Geoapify routing integration, the priority queue scheduling algorithm, the Gemini symptom extraction call.

**What didn't:** the fine-tuned Vertex AI endpoint was never successfully wired into the cloud function after 8 attempted endpoint URL formats — the deployed version silently substitutes random classification for real model inference. The frontend and backend never communicated. The severity schemas between the two layers were incompatible.

The codebase is a collection of parallel exploration tracks that were not consolidated before the demo. It reads like a hackathon, because it was one.

---

## Current State (as of May 2026 audit)

| Layer | Status |
|---|---|
| React SPA (3 tabs: Smart Routing, In-house Scheduling, Predictive Analysis) | Working as standalone simulation |
| Geoapify Route Matrix integration | Working (API key hardcoded — not safe to deploy) |
| Priority queue triage algorithm | Working |
| Gemini 2.5 Flash symptom extraction (Cloud Function) | Working given valid GCP credentials |
| Fine-tuned Vertex AI severity classifier | Broken — never successfully called; random fallback deployed |
| Frontend ↔ Backend integration | None — fully isolated subsystems |
| Severity schema consistency | Broken — two incompatible 4-class schemas across layers |
| Environment / secrets management | None — keys hardcoded in client-side source |
| CI/CD, Docker, infrastructure config | None |

See [`CHANGELOG.md`](./CHANGELOG.md) for the full known-issues inventory from the hackathon release.

---

## New Direction — v2.0

The rebuild moves from a simulation demo to an integrated AI-powered product with a real user session flow.

### Product Vision

The home page presents a split interface: a conversational chat panel on the left, a live Leaflet map of Toronto on the right centered on the CN Tower with nearby medical facilities marked.

The user flow:

1. User types how they feel in the chat panel — free text, no structured form
2. The AI agent runs a parallelized tool workflow:
   - **Tool 1a** — Claude (Anthropic API) parses the input and returns structured severity classification (`routine / moderate / urgent / emergent`) with reasoning
   - **Tool 1b** — Browser Geolocation API captures the user's position (with explicit consent prompt)
3. On both results returning, a second tool call fires:
   - **Tool 2** — Geoapify RouteMatrix computes travel times from the user to all nearby facilities; the system selects the most appropriate facility given severity class
4. The map updates in real time: user pin appears, route polyline draws, destination facility highlights
5. The chat responds with a plain-language explanation of the recommendation and why — not just a name and address
6. Optionally: a user-initiated contact alert panel appears for high-severity classifications (user taps to send — never autonomous)

The tool-calling pipeline is made visible in the chat UI with a live progress trace during the parallel step, so the AI engineering is legible to both end users and technical evaluators.

### Architecture (v2.0 Target)

```
Browser
├── Chat Panel (left)
│   ├── User symptom input
│   ├── Tool trace UI (parallel step progress)
│   └── Claude response with recommendation + reasoning
└── Map Panel (right)
    ├── Facility markers (static, 43 Toronto providers)
    ├── User pin (from geolocation, this session)
    └── Route polyline (drawn after Tool 2 resolves)

Backend API
├── POST /triage
│   ├── Tool 1a: Anthropic API → severity classification (structured output)
│   ├── Tool 1b: Geolocation payload from client
│   └── Tool 2: Geoapify RouteMatrix → nearest appropriate facility
└── (Optional) POST /alert — user-initiated contact notification

Infrastructure
├── Environment variables for all API keys (no hardcoded secrets)
├── requirements.txt for Python services
├── Docker config for backend
└── GitHub Actions CI/CD (lint, type-check, deploy gate)
```

### What Changes from the Hackathon Build

- The Vertex AI fine-tuned classifier is retired. Claude handles severity classification natively via structured tool output — more reliable, no endpoint management, better accuracy than a 238-sample fine-tune
- The simulation engine is not the product anymore. The map responds to this user's real session, not synthetic patients
- Frontend and backend are connected through a real API contract with a shared severity schema
- The Dialogflow CX dependency is dropped — the agentic workflow is implemented directly via the Anthropic API tool-calling interface

---

## Performance

Load-tested in Sprint 22 (2026-10-13) with k6 against the deployed API on a single
1 vCPU / 1 GB instance. LLM and routing calls ran through a provider mock calibrated
against 1,935 real OpenAI turns (mean 1.69 s and p95 within 2% of real).
Sprint details: [CHANGELOG.md](CHANGELOG.md) (Sprint 22).

| Result | Value |
|---|---|
| Throughput, one instance | ~35 chat turns/s (2,100/min), ~16 ms API CPU per turn |
| Admission control at 2.5x capacity | accepted turns p95 3.3 s (10.3 s without it); excess gets a fast retry-after answer |
| 60-minute soak | 93,322 turns, 0 failures, p95 2.6 s, memory flat (+0.2%) |
| Breakpoint run | 14,238 turns, 0 failures; past ~60 turns in flight it queues instead of failing |
| DB pool sizing | measured: pool 5 beats 10 and 20 on one vCPU (control run reproduced) |

Next: an async database pool and a 2-worker box, re-measured with the same ladder.

---

## Tech Stack

**Current (hackathon build)**
- React 18 + Vite + TypeScript + Tailwind CSS
- React Leaflet / Leaflet
- Geoapify Route Matrix API
- GCP: Cloud Functions (Python), Vertex AI, Firestore
- Gemini 2.5 Flash (symptom extraction)
- `@faker-js/faker` (synthetic patient generation)

**Target (v2.0)**
- React 18 + Vite + TypeScript + Tailwind CSS
- React Leaflet / Leaflet
- Anthropic API (Claude) — agentic tool-calling, severity classification, chat
- Geoapify Route Matrix API
- Backend API layer (Node/Python TBD)
- Secure environment variable management

---

## Repository Structure

```
medicoordai/
├── webapp/                        # React/Vite SPA
│   └── src/
│       ├── App.tsx
│       ├── Menucomponents/
│       │   ├── Home.tsx           # Smart Routing tab
│       │   ├── Inhousescheduler.tsx # In-house Scheduling tab
│       │   ├── Map.tsx            # Predictive Analysis tab
│       │   ├── subcomponent/
│       │   │   ├── MapPanel.tsx
│       │   │   └── SimulationForm.tsx
│       │   └── utils/
│       │       ├── baseData.ts    # 43 Toronto health providers
│       │       ├── geoapify.ts    # Route Matrix API client
│       │       ├── priorityQueue.ts # Binary min-heap triage sorter
│       │       ├── generator.ts
│       │       ├── formatter.ts
│       │       └── customIcon.tsx
├── cloud_function/
│   ├── triage_function_original.py  # Broken Vertex AI integration
│   └── triage_function_alternate.py # Deployed fallback (random classifier)
├── fine_tuning_training/            # 238-sample severity dataset (archived)
├── backup/                          # Earlier Python triage iterations
└── CHANGELOG.md
```

---

## Hackathon Team

Built at Toronto Tech Week 2025.  
Technologies: Python · GCP Vertex AI · Gemini 2.5 · React.js · Geoapify · Leaflet

---

## Status

> **This project is in active redesign.**  
> The hackathon build is preserved on `main` as the baseline. v2.0 development begins from the audit completed May 2026.