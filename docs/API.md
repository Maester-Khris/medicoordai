# API Contract — MediCoord AI

All types referenced here are defined in `shared/types.ts` (TypeScript) and mirrored as Pydantic models in `backend/models.py`. When these diverge, `shared/types.ts` is the source of truth.

Any change to an endpoint, request shape, or response shape in this file requires a corresponding update to both `shared/types.ts` and `backend/models.py` before implementation begins.

---

## Base URLs

| Environment | Frontend origin | Backend base URL |
|---|---|---|
| Local dev | `http://localhost:5173` | `http://localhost:8000` |
| Vercel preview | `https://<branch>.medicoord.vercel.app` | `https://medicoordai-staging-production.up.railway.app` (Railway staging) |
| Production | `https://medicoord.vercel.app` | Railway production service domain (see Railway dashboard) |

CORS: The backend allows requests from Vercel preview URLs and the production frontend origin. Configured in `backend/main.py`.

---

## Endpoints — Phase 1

### POST `/triage`

The primary endpoint. Accepts a user's symptom message and location, returns a structured triage result with routing information.

**Request**
```json
{
  "message": "I've had a sharp chest pain for the last 20 minutes and my left arm feels numb",
  "lat": 43.6532,
  "lng": -79.3832
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `message` | `string` | Yes | Raw user input, 1–2000 chars |
| `lat` | `number` | Yes | User latitude from browser geolocation |
| `lng` | `number` | Yes | User longitude from browser geolocation |

**Response `200`**
```json
{
  "severity": "emergent",
  "reasoning": "Chest pain with left arm numbness is a classic presentation of acute myocardial infarction. Immediate emergency care is required.",
  "facility": {
    "id": "uuid",
    "name": "Toronto General Hospital",
    "category": "hospital",
    "source_facility_type": "general",
    "accepted_severity": ["emergent", "urgent", "moderate", "routine"],
    "address": "200 Elizabeth St, Toronto, ON M5G 2C4",
    "lat": 43.6590,
    "lng": -79.3887,
    "source": "odhf"
  },
  "travelMinutes": 6,
  "distanceKm": 1.2,
  "toolTrace": [
    { "tool": "classify_severity", "status": "done", "durationMs": 820 },
    { "tool": "route_matrix", "status": "done", "durationMs": 340 }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `severity` | `Severity` | One of `routine \| moderate \| urgent \| emergent` |
| `reasoning` | `string` | Plain-language explanation for the recommendation |
| `facility` | `Facility` | Selected facility object |
| `travelMinutes` | `number` | Estimated driving time from user to facility |
| `distanceKm` | `number` | Driving distance |
| `toolTrace` | `ToolTrace[]` | Ordered log of tools called — used by frontend progress UI |

**Response `422`** — Validation error (malformed request body)
```json
{
  "detail": [{ "loc": ["body", "lat"], "msg": "field required", "type": "value_error.missing" }]
}
```

**Response `503`** — LLM provider or Geoapify unavailable
```json
{
  "error": "upstream_unavailable",
  "message": "Classification service unavailable. Please try again.",
  "retryAfterSeconds": 5
}
```

---

### GET `/health`

Liveness check. Used by Railway to confirm the service is running.

**Response `200`**
```json
{ "status": "ok", "llmProvider": "groq" }
```

---

### POST `/routes`

Travel routes from the caller's position to up to three candidate facilities, for one travel
mode. One Geoapify Routing call per candidate, made in parallel by the backend. The browser never
calls Geoapify.

**Auth:** guest (`X-Guest-Id`) under `DEMO_MODE`, otherwise a signed-in user.
**Rate limit (guests):** 60 per guest and 180 per IP per 600 s, separate from the chat limit.

Request:

```json
{ "origin": { "lat": 43.6532, "lng": -79.3832 }, "facility_ids": ["<id>", "<id>"], "mode": "bike" }
```

`facility_ids`: 1 to 3, unique, resolved against the server's facility list. `mode`: `car`,
`bike`, `bus` or `walk` (Geoapify `drive`, `bicycle`, `transit`, `walk`).

Response 200:

```json
{
  "mode": "bike",
  "routes": [
    { "facility_id": "<id>", "eta_minutes": 34, "distance_km": 9.8, "geometry": [[43.65, -79.38], [43.66, -79.39]] },
    { "facility_id": "<id>", "eta_minutes": null, "distance_km": null, "geometry": null }
  ],
  "fastest_facility_id": "<id>"
}
```

`geometry` is a list of `[lat, lng]` pairs. A candidate that could not be routed has nulls.

| Status | Meaning |
|---|---|
| 422 | Invalid body, or a mode that is not enabled |
| 404 | A facility id is unknown |
| 429 | Guest over the routes limit (`{"code": "busy", "retry_after": <seconds>}`) |
| 502 | No candidate could be routed |
| 503 | Routing not configured, or the facility list is not loaded |

### POST `/events`

Guest-only measurement events. Body:

```json
{ "type": "mode_changed", "session_id": "<uuid>", "mode": "walk", "duration_ms": 840 }
```

| `type` | `mode` | `duration_ms` | Rows per session |
|---|---|---|---|
| `route_drawn` | optional | not allowed | one |
| `mode_changed` | required | optional, 0–120000, browser time from click to redraw | many |

Returns 204. `session_started` and `recommendation_shown` are written by the server and cannot be
posted.

### GET `/facilities/nearby`

Query: `lat`, `lng`, `radius_m` (default 5000, capped at 50000), optional `category`, optional
`max_wait_minutes`. Returns up to 50 facilities, nearest first. Under `DEMO_MODE` the search runs
on the in-memory facility list with a straight-line distance; the three `eta_*_min` fields are
fixed-speed estimates kept for the response shape and are not travel times from a routing engine.

## Operations: metrics and settings

### GET `/metrics`

Prometheus text format. **Auth:** `Authorization: Bearer <METRICS_BEARER_TOKEN>`. Answers 503
when the token is not configured and 403 on a wrong one. Grafana Cloud scrapes this endpoint
(Metrics Endpoint integration); the API pushes nothing.

Counters and histograms live in the process and restart with it. The API runs as one worker;
with several workers each would report its own numbers.

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total`, `http_request_duration_seconds` | per route | `handler`, `method`, `status` |
| `llm_call_duration_seconds` | histogram | `provider`, `outcome` |
| `llm_calls_total` | counter | `provider`, `outcome` (`ok`, `rate_limited`, `timeout`, `error`) |
| `llm_tokens_total` | counter | `provider`, `kind` (`prompt`, `completion`) |
| `routing_call_duration_seconds` | histogram | `mode`, `outcome` (`ok`, `no_route`, `timeout`, `error`) |
| `graph_lookup_duration_seconds` | histogram | `provider` (value of `GRAPH_RAG_PROVIDER`), `outcome` |
| `demo_db_pool_size`, `demo_db_pool_in_use`, `demo_db_pool_waiting` | gauge | none |

### Settings

Read at call time. A missing, malformed or out-of-range number falls back to the default with
one `env_setting_invalid` warning.

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_DB_POOL_MAX` | 5 (1 to 50) | Largest number of demo database connections |
| `DEMO_DB_POOL_TIMEOUT_SECONDS` | 5 (1 to 60) | How long a request waits for a free connection |
| `RATE_LIMIT_CHAT_GUEST`, `RATE_LIMIT_CHAT_IP` | 10, 30 | Chat messages per guest and per IP per 10 minutes |
| `RATE_LIMIT_ROUTES_GUEST`, `RATE_LIMIT_ROUTES_IP` | 60, 180 | Route requests per guest and per IP per 10 minutes |
| `LLM_TIMEOUT_SECONDS` | 30 (1 to 300) | Timeout of one provider call |
| `LLM_PROVIDER` | `groq` | Single provider: `groq`, `openai` or `anthropic` |
| `LLM_PROVIDER_CHAIN` | unset | Ordered fallback, for example `groq,openai,anthropic`. Wins over `LLM_PROVIDER` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | none | Required for the `openai` provider. The model has no default |

The rate-limit variables exist for load tests on staging; the public demo keeps the defaults.

### LLM provider fallback

With `LLM_PROVIDER_CHAIN` set, a chat call goes to the first provider and moves to the next one
when the failure belongs to that provider: rate limit (429), timeout, server error (5xx),
connection failure, or rejected credentials (401, 403). Any other error is raised at once. Each
provider is tried once per call, with its SDK retries off. A switch logs `llm_fallback` with
`from_provider`, `to_provider` and `outcome`, and both attempts appear in `llm_calls_total`.

Do not enable a chain for guests before the triage vignette check has run on every model in it:
a different model can classify severity differently.

## Shared Types Reference

Canonical definitions live in `shared/types.ts`. Replicated here for documentation.

```typescript
export type Severity         = "routine" | "moderate" | "urgent" | "emergent";
export type FacilityCategory = "hospital" | "ambulatory" | "residential";

export interface Facility {
  name:                 string;
  category:             FacilityCategory;
  source_facility_type: string;
  accepted_severity:    Severity[];
  address:              string;
  lat:                  number;
  lng:                  number;
  id?:                  string;
  source?:              string;
  created_at?:          string;
  updated_at?:          string;
}

export interface TriageRequest {
  message: string;
  lat:     number;
  lng:     number;
}

export interface ToolTrace {
  tool:        string;
  status:      "pending" | "done" | "error";
  durationMs?: number;
}

export interface TriageResult {
  severity:      Severity;
  reasoning:     string;
  facility:      Facility;
  travelMinutes: number;
  distanceKm:    number;
  toolTrace:     ToolTrace[];
}
```

---

## LLM Tool Definitions

The backend passes the following tools to the LLM client. Tool schemas are defined in `backend/llm/tools.py`.

### `classify_severity`
Used in parallel step (Tool 1a).

```json
{
  "name": "classify_severity",
  "description": "Classify the severity of a patient's symptoms into one of four triage levels.",
  "input_schema": {
    "type": "object",
    "properties": {
      "severity": {
        "type": "string",
        "enum": ["routine", "moderate", "urgent", "emergent"]
      },
      "reasoning": {
        "type": "string",
        "description": "Plain-language explanation of the classification for the patient"
      },
      "symptoms": {
        "type": "array",
        "items": { "type": "string" },
        "description": "List of up to 5 discrete symptoms extracted from the message"
      }
    },
    "required": ["severity", "reasoning", "symptoms"]
  }
}
```

### `get_nearest_facility`
Used in chained step (Tool 2) — called after severity is known.

```json
{
  "name": "get_nearest_facility",
  "description": "Given a severity level and user location, return the nearest appropriate facility and routing information.",
  "input_schema": {
    "type": "object",
    "properties": {
      "severity": { "type": "string", "enum": ["routine", "moderate", "urgent", "emergent"] },
      "userLat": { "type": "number" },
      "userLng": { "type": "number" }
    },
    "required": ["severity", "userLat", "userLng"]
  }
}
```

This tool is implemented server-side: when the LLM calls it, the backend executes the Geoapify RouteMatrix call and returns the result — the LLM does not call Geoapify directly.

---

## Geoapify Integration

**Endpoint:** `POST https://api.geoapify.com/v1/routematrix`  
**Called by:** Backend only (never frontend)  
**Auth:** `GEOAPIFY_API_KEY` env var injected via Doppler, used by the backend only. There is no browser key.
**Mode:** `drive`  
**Sources:** `[{ lat: userLat, lon: userLng }]`  
**Targets:** All facilities whose `acceptedSeverity` includes the classified severity level

Response matrix is sorted by `time` ascending. The first result is selected as the recommended facility.

---

## Future Endpoints (Phase 2 — not yet implemented)

| Endpoint | Purpose |
|---|---|
| `POST /session` | Create a persistent session (requires Supabase) |
| `POST /alert` | User-initiated emergency contact notification |
| `GET /facilities` | Return the full facility dataset (implemented in Phase 1, busyness field deferred) |