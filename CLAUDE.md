# MediCoord AI — Claude Code Project Context

## Project in One Sentence
A city-wide health coordination system where users describe symptoms in a chat interface and an AI agent routes them to the nearest appropriate facility on a live map.

## Repository Structure
```
medicoordai/
├── backend/          # FastAPI — triage API, LLM tool orchestration
├── webapp/           # React + Vite + TypeScript — chat + map UI
├── shared/           # Shared TypeScript types (severity schema, API contracts)
├── docs/             # Architecture, ADRs, API contract
├── .claude/          # This folder
└── .github/          # CI/CD workflows
```

## Tech Stack (non-negotiable, do not suggest alternatives)
- **Frontend:** React 18, Vite, TypeScript (strict), Tailwind CSS
- **Backend:** Python 3.11, FastAPI
- **AI:** Groq (primary, free tier) or Anthropic Claude — controlled via feature flag `LLM_PROVIDER`
- **Routing:** Geoapify Route Matrix API
- **Auth / DB:** Supabase — not in scope for current phase, do not scaffold yet
- **Env vars:** Doppler — all `run` commands must use `doppler run --`
- **Frontend deploy:** Vercel (preview on PR, production on main)
- **Backend deploy:** Railway (web service + cron/worker services; deploy via Railway CLI from `backend/`)


## Running Commands

### Python virtualenv
Always activate the pydev virtualenv before any Python or dbt command:
```bash
source /home/niki/Documents/workenv/pydev/bin/activate
```
This applies to all Python, pip, dbt, pytest, and uvicorn invocations.

### Environment variables
Inject environment variables via Doppler when they are not already exported:
```bash
# Backend
doppler run -- uvicorn backend.main:app --reload

# Frontend
doppler run -- npm run dev

# Tests
doppler run -- pytest
doppler run -- npm run test
```
If env vars are already exported in the shell session, skip Doppler.
Never hardcode secrets. Never use a raw `.env` file in commands.


## Current Scope (Phase 1)
**In scope:** User ↔ chatbot interaction only.
- Symptom input → severity classification → facility routing → map response
- `/triage` endpoint and LLM tool orchestration

**Out of scope (do not implement or scaffold):**
- Supabase auth or database integration
- Emergency contact notifications
- Predictive analytics tab
- Admin dashboard

## Severity Schema — Single Source of Truth
Defined in `shared/types.ts`. The four valid values are:
```
routine | moderate | urgent | emergent
```
Never use: `critical`, `severe`, `high`, `low`, or any synonym. If you see these in existing code, flag it — do not silently fix it without noting it in your task summary.

## Code Conventions
- TypeScript: strict mode, no `any`, all props interfaces defined
- Python: type hints on all function signatures, Pydantic models for all request/response bodies
- New backend routes: matching type must exist in `shared/types.ts` first
- No new npm packages without noting it in the task summary
- No new Python dependencies without adding to `requirements.txt`

## Git Rules
- Never add Claude as a co-author on commits
- Commit style: conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`)
- Never commit directly to `main` or `preview` — both are protected
- Branch naming: `feat/`, `fix/`, `refactor/`, `chore/`, `docs/` prefixes — always cut from `preview`
- One commit per logical change, not per file — all files belonging to the same
  task are staged and committed together in a single `git add <f1> <f2> ...` call.
  Never produce one commit per file.

## Custom Commands
- `/audit` — read-only feature inventory of the entire codebase
- `/execute-task <filename>` — full task lifecycle: read `.agents/tasks/<filename>`, plan, wait for approval, implement, optional tests, outcome summary, git commit
- `/start-sprint "<title>" <branch>` — pull `preview`, create and push feature branch, mark sprint as started in CHANGELOG.md, commit changelog entry
- `/end-sprint "<pr message>"` — commit all unstaged work on the current feature branch, push, and open a PR to `preview`. Never runs on `main` or `preview`.


## Sprint Lifecycle
```
/start-sprint "title" feat/branch-name   ← creates branch, updates changelog
  /execute-task 00N-task-name.md         ← one or more tasks
  /execute-task 00N-task-name.md
/end-sprint "pr message"                 ← commits remainder, pushes, opens PR
```
 

## Before Big Tasks
For any task that spans more than one file or changes an API contract:
1. Write a short plan (what you'll change, what you won't touch, any open questions)
2. Wait for explicit approval before implementing
3. After implementing, summarize what changed and flag any deviations from the plan

## Key Files to Read First
- `docs/ARCHITECTURE.md` — system design and data flow
- `docs/API.md` — endpoint contracts and request/response shapes
- `shared/types.ts` — severity schema and shared interfaces
- `AGENTS.md` — behavioral rules for this repo

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
