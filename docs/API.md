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
**Auth:** `GEOAPIFY_API_KEY` env var injected via Doppler  
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