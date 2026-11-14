import type { ElementType } from 'react'
import { TreeStructure, Compass, ChartLineUp, FlowArrow, Gauge, ShareNetwork, Target } from '@phosphor-icons/react'
import type { MetricBullet } from '../utils/caseStudyContent'
import twoPassTriageDiagram from '../assets/case-studies/two-pass-tool-orchestration-symptom-triage.png'
import haversineProximityDiagram from '../assets/case-studies/haversine-proximity-severity-gated-eligibility.png'
import twoTierCacheDiagram from '../assets/case-studies/two-tier-facility-state-cache-redis-wait-times.png'
import eventDrivenFanOutDiagram from '../assets/case-studies/event-driven-fan-out-eventbridge-serverless-pipeline.png'
import twoTrackEvalDiagram from '../assets/case-studies/two-track-llm-evaluation-groundedness-faithfulness.png'

export interface DiagramStep {
  title: string
  desc: string
  icon: string
}

export interface ProblemHighlight {
  heading: string
  body: string
  accent: 'danger' | 'info'
}

export interface CodeSample {
  filename: string
  language: string
  content: string
}

export interface NamedSection {
  title: string
  body: string
}

export interface DiagramImage {
  src: string
  alt: string
  caption: string
}

export type NavSection = 'architecture' | 'infrastructure' | 'ai-models' | 'security' | 'change-logs'
export type CaseStudyAccent = 'mint' | 'blue'

export interface CaseStudy {
  slug: string
  navSection: NavSection
  category: string
  accent: CaseStudyAccent
  icon: ElementType
  tags: string[]
  title: string
  readTimeMinutes: number
  publishedDate: string
  updatedDate?: string
  author: string
  summary: string
  background?: string
  problem: string
  problemHighlights: ProblemHighlight[]
  alternativesConsidered?: NamedSection[]
  approach: string
  approachEmphasis: [string, string]
  code?: CodeSample
  codeSamples?: CodeSample[]
  diagramSteps: DiagramStep[]
  diagramImage?: DiagramImage
  lessonsLearned?: NamedSection[]
  tradeoff: string
  result: MetricBullet[]
  resultOrdered?: boolean
  methodology?: MetricBullet[]
  methodologyOrdered?: boolean
}

export const CASE_STUDIES: CaseStudy[] = [
  {
    slug: 'two-pass-tool-orchestration-symptom-triage',
    navSection: 'ai-models',
    category: 'LLM Symptom Understanding',
    accent: 'mint',
    icon: TreeStructure,
    tags: ['#AI-Agents', '#LLMTools', '#Groq', '#Evals'],
    title: 'Two-Pass Tool Orchestration for Symptom Triage',
    readTimeMinutes: 7,
    publishedDate: '2026-05-10',
    updatedDate: '2026-07-12',
    author: 'MediCoord Core Platform Team',
    summary:
      "Splitting LLM symptom triage into two forced passes: a tool-only severity classification, then a deterministic facility lookup, then a grounded response, so the model can never invent a facility name or commit to a severity before it has enough information — then proving it holds with two independent evaluation tracks: an online deterministic check against simulated live traffic, and an offline LLM-as-judge pass over a purpose-built dataset.",
    background:
      "MediCoord's chat interface routes patients to the nearest appropriate facility based on a short symptom conversation. The riskiest part of that pipeline isn't the routing. It's the classification. A large language model asked to output severity directly, in one shot, will produce a confident, well-formatted answer whether or not it actually has enough information. We split triage into two passes so the model's linguistic fluency and Python's determinism each do the job they're actually good at. Splitting the pipeline is a design decision; proving it holds is a separate discipline. An LLM's behavior can't be verified by reading the code that calls it, so evaluation isn't a QA afterthought bolted on at the end — it's built as two independent tracks that each catch a different failure mode: a zero-cost deterministic check that runs on every request against simulated live traffic, and an offline pass where a second model judges faithfulness against a dataset purpose-built to exercise this exact pipeline.",
    problem:
      "Two failure modes show up when you let a single LLM call do both classification and response generation. First, models are trained to be helpful, which means they'll often generate a plausible-sounding facility name and address instead of admitting they don't have one, and there's no reliable way to catch that after the fact once it's already in a patient-facing sentence. Second, models are eager: given three words of symptom description, an unconstrained model will confidently commit to a severity level rather than asking a clarifying question first. Both failure modes are worse than a slow response: a wrong facility name sends a patient to the wrong door, and a premature classification is either a false alarm or a missed one.",
    problemHighlights: [
      {
        heading: 'Hallucinated Facilities',
        body: 'A model asked to write "the nearest facility is X" in the same breath as reasoning about symptoms has no way to guarantee X is a real place. It is optimizing for a plausible sentence, not a grounded fact.',
        accent: 'danger',
      },
      {
        heading: 'Premature Classification',
        body: 'Nothing stops a one-shot model from committing to a severity level on the first message, before it has asked about duration, associated symptoms, or history.',
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: 'Single-pass classify-and-respond',
        body: "The simplest design is one LLM call that both classifies severity and writes the response in the same completion. We prototyped this first: it's faster (one round trip) and simpler to implement. It broke exactly the way you'd expect: the model would generate specific-sounding facility names that didn't exist in our data, and there was no clean place to intercept and correct a hallucinated fact inside an already-generated sentence.",
      },
      {
        title: 'Structured output / JSON mode instead of tool calling',
        body: "We considered constraining the single-pass response with a JSON schema instead of splitting into two calls. That solves the format problem but not the grounding problem: a well-formed JSON object can still contain an invented facility name. Tool calling forced us to physically remove the facility field from what the model is allowed to write in pass one, which JSON mode alone doesn't do.",
      },
    ],
    approach:
      "triage_response is the only tool the model can call in Pass 1, and its schema forces a severity enum (routine, moderate, urgent, emergent) plus a short internal reasoning string and an information_sufficient boolean: no patient-facing text, no facility name, nothing the model could invent. A minimum-turns gate suppresses that tool call as a followup question unless the model has already seen enough of the conversation, unless severity comes back 'emergent' or the conversation has hit a hard turn ceiling, both of which bypass the gate, because refusing to route an emergency to force more questions is its own failure mode. Once severity is classified, Pass 2 is deterministic: a plain Python function looks up the nearest eligible facility from the in-process cache, no LLM involved, and returns a real facility record. That record is injected into a second grounding message before asking the model to write the two-to-four sentence patient-facing reply. The model never gets a chance to invent a name because by the time it's writing prose, the name is already a fact in its context, not a decision it's making.",
    approachEmphasis: ['no patient-facing text, no facility name, nothing the model could invent', 'The model never gets a chance to invent a name'],
    codeSamples: [
      {
        filename: 'tools.py',
        language: 'python',
        content: `TRIAGE_RESPONSE = ToolDefinition(
    name="triage_response",
    description=(
        "Call this when you have sufficient information to classify the "
        "patient's symptom severity. Do NOT include a patient-facing "
        "response — the conversational response is generated separately "
        "after the nearest facility is identified from the system's data. "
        "Never invent or guess facility names."
    ),
    parameters={
        "severity": {
            "type": "string",
            "enum": ["routine", "moderate", "urgent", "emergent"],
        },
        "reasoning": {"type": "string"},
        "information_sufficient": {"type": "boolean"},
    },
    required=["severity", "reasoning", "information_sufficient"],
)`,
      },
      {
        filename: 'llm_agent.py',
        language: 'python',
        content: `if facility:
    facility_fact = (
        f"The nearest appropriate facility is: {facility['name']} "
        f"at {facility['address']}, approximately "
        f"{facility['distanceKm']} km away. Use this exact facility "
        f"name in your response — do not modify or replace it."
    )
else:
    facility_fact = (
        "No location data is available. Do not mention any specific "
        "facility. Advise the patient to call 211 or search online "
        "for nearby care."
    )`,
      },
    ],
    diagramSteps: [
      { title: 'User Message In', desc: 'Chat turn appended to trimmed conversation history (last TRIAGE_CONTEXT_WINDOW messages).', icon: 'ti ti-message-chatbot' },
      { title: 'Pass 1: Forced Tool Call', desc: 'LLM emits triage_response: severity, reasoning, information_sufficient. No facility data yet.', icon: 'ti ti-braces' },
      { title: 'Deterministic Facility Lookup', desc: 'Python calls find_nearest_facilities() against the in-process cache. No LLM involved.', icon: 'ti ti-git-fork' },
      { title: 'Pass 2: Grounded Response', desc: 'Real facility name injected into a system message; LLM writes the patient-facing reply.', icon: 'ti ti-brain' },
    ],
    diagramImage: {
      src: twoPassTriageDiagram,
      alt: 'Diagram of the two-pass triage flow: a forced tool call classifies severity, Python looks up the nearest facility deterministically, then a grounded second pass writes the patient-facing response',
      caption: 'FIG 1.1: TWO-PASS TRIAGE PIPELINE',
    },
    lessonsLearned: [
      {
        title: "finish_reason isn't the signal to trust",
        body: 'The Groq/Llama models we use will sometimes return both a text completion and a tool_calls array in the same response. Early logic branched on finish_reason and occasionally dropped a valid tool call. The fix was to treat a non-empty tool_calls list as authoritative regardless of finish_reason.',
      },
      {
        title: 'Emergency cases need their own bypass',
        body: "The minimum-turns gate was originally unconditional. That meant a first message like 'chest pain, can't breathe' would get a clarifying question instead of an immediate route. We added an explicit bypass: an emergent classification skips the gate no matter how early in the conversation it fires.",
      },
    ],
    tradeoff:
      "Two passes mean two LLM round trips instead of one, adding latency to every triage decision, acceptable for a chat interface, less so if this were a high-throughput batch job. The min-turns gate is also a blunt instrument: it counts user turns, not information content, so a chatty user who says a lot in one message still waits, and a terse user who needs more prompting can still get force-classified at the turn ceiling with information_sufficient: false. What's next: a knowledge-graph grounding step sourced from Canadian diagnostic data is in active development this week, aimed at the classification step itself. Today's two-pass design is the orchestration layer that step will plug into, not a replacement for it.",
    result: [
      { text: 'Validated by two independent evaluation tracks — a zero-cost deterministic groundedness check and an offline LLM-as-judge faithfulness score — see Case Study: Two-Track LLM Evaluation for full methodology and measured results.', bold: [] },
    ],
    methodology: [
      { text: 'See Case Study: Two-Track LLM Evaluation for full methodology.', bold: [] },
    ],
  },
  {
    slug: 'haversine-proximity-severity-gated-eligibility',
    navSection: 'architecture',
    category: 'Proximity Search',
    accent: 'blue',
    icon: Compass,
    tags: ['#Geospatial', '#Routing', '#Python'],
    title: 'Haversine Proximity + Severity-Gated Eligibility',
    readTimeMinutes: 7,
    publishedDate: '2026-05-17',
    updatedDate: '2026-07-14',
    author: 'MediCoord Core Platform Team',
    summary:
      'Filtering facilities by severity eligibility before ranking by distance, using a plain Haversine calculation over an in-process cache, fast enough for the inline triage path, with the ranked candidate list already shaped for a future travel-time upgrade.',
    background:
      "Every triage decision needs to answer one question fast: which facilities, out of MediCoord's full facility directory, can actually take this patient right now? This filter runs on every request, so it needs to be correct and cheap before it needs to be clever.",
    problem:
      "A naive 'closest facility' query just sorts by distance. But distance alone can send a patient to a facility that's wrong for their condition: a routine-only clinic showing up ahead of a hospital that can actually treat an emergent case, or the reverse. Ranking has to happen after eligibility is decided, not before, and it has to run inside the latency budget of a chat response, with no room for a slow query across the full facility table on every message.",
    problemHighlights: [
      {
        heading: 'Eligibility Before Ranking',
        body: "A facility 500m away that doesn't accept the patient's severity level isn't 'close'. It's not a candidate. Filtering has to run before distance sorting, not after.",
        accent: 'danger',
      },
      {
        heading: 'Latency Budget',
        body: 'Proximity search runs inline in the triage response path. It has to return in milliseconds, not seconds, or it becomes the slowest part of every chat turn.',
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: 'PostGIS spatial index (ST_DWithin / ST_Distance)',
        body: "This is the more scalable answer, and it's already scoped as a follow-up: the function returns its full ranked candidate list specifically so a future re-rank by real travel time can happen without any backend change. We didn't reach for PostGIS first because the facility count in a single-city directory is small enough that an in-memory linear scan is faster to ship and easier to reason about than standing up a spatial index, tuning it, and keeping it in sync with a Supabase table that already changes on its own schedule.",
      },
      {
        title: 'Precomputed distance matrix',
        body: "Precomputing distances from every facility to a grid of coordinates would make lookups near-instant, but the input isn't a grid point. It's wherever the patient happens to be standing, at whatever precision their device reports. Precomputing against irregular real-world GPS input means either snapping to a grid, which adds error exactly where distance accuracy matters most, or recomputing anyway, which defeats the purpose.",
      },
    ],
    approach:
      "find_nearest_facilities() does two things in a fixed order: filter, then sort. It reads the full facility list from an in-process cache, populated ahead of time from Supabase and not queried per-request, keeps only facilities where the requested severity appears in that facility's accepted_severity array, then ranks the survivors by Haversine great-circle distance, the standard spherical-law-of-cosines formula, with no external geo library. The top N (defaulting to 3, tunable by environment variable) go back to the caller, with the nearest becoming the recommended facility and the rest returned as alternatives. Distance is computed at request time, not pre-materialized, because the input point (the patient's current GPS coordinates) is different on every call; there's nothing to precompute.",
    approachEmphasis: ['filter, then sort', 'nothing to precompute'],
    codeSamples: [
      {
        filename: 'proximity.py',
        language: 'python',
        content: `def haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def find_nearest_facilities(lat, lng, severity, top_n=None) -> list[dict] | None:
    facilities, _ = get_cached_facilities()
    if facilities is None:
        return None

    eligible = [f for f in facilities if severity in f.get("accepted_severity", [])]
    if not eligible:
        return []

    ranked = sorted(
        [{**f, "distanceKm": round(haversine_km(lat, lng, f["lat"], f["lng"]), 2)} for f in eligible],
        key=lambda x: x["distanceKm"],
    )
    return ranked[:top_n or TOP_N_DEFAULT]`,
      },
    ],
    diagramSteps: [
      { title: 'Location + Severity In', desc: 'Patient GPS coordinates and classified severity from Pass 1 of triage.', icon: 'ti ti-map-pin' },
      { title: 'In-Process Cache Read', desc: 'Full facility list read from the app-layer cache. No per-request database query.', icon: 'ti ti-database' },
      { title: 'Severity Eligibility Filter', desc: 'Keep only facilities where accepted_severity includes the requested level.', icon: 'ti ti-filter' },
      { title: 'Haversine Ranking', desc: 'Sort eligible facilities by great-circle distance; return top N with distanceKm attached.', icon: 'ti ti-calculator' },
    ],
    diagramImage: {
      src: haversineProximityDiagram,
      alt: 'Diagram of the proximity pipeline: read the in-process facility cache, filter by severity eligibility, then rank survivors by Haversine distance',
      caption: 'FIG 2.1: PROXIMITY FILTER-THEN-RANK PIPELINE',
    },
    lessonsLearned: [
      {
        title: 'The cache can legitimately be empty',
        body: "find_nearest_facilities() returns None (not an empty list) when the facilities cache itself hasn't been populated yet, a real state during cold start or a Supabase outage. Early logic conflated that with 'zero facilities match this severity', which returns an empty list. Callers need to check for None explicitly: 'we don't have data yet' is not the same message to a patient as 'no facility currently accepts this severity.'",
      },
      {
        title: 'top_n is not the same as eligible count',
        body: "The result cap limits how many results come back, not how many exist. A severity with only one eligible facility in the whole directory correctly returns a list of one. The function doesn't pad or backfill with ineligible facilities to hit the cap.",
      },
    ],
    tradeoff:
      "Haversine gives straight-line distance, and straight-line distance is a known approximation of how long it actually takes to get somewhere: a facility 1.5km away across a highway can be slower to reach than one 4km away with a direct route. That gap is real and we're not hiding it: it's exactly the gap the roadmap item below closes. In the meantime, the eligibility filter (can this facility even take this patient) is correct today; only the ranking within the eligible set is an approximation. What's next: the function already returns its full ranked candidate list to the frontend for this reason. A composite score combining real travel time from a routing API with live queue depth can replace the Haversine sort without changing this function's contract, once that data exists.",
    result: [
      { text: '1.21 km average routing error (Haversine vs. real driving distance) across 30 shadow-call samples, spread across 400 triage requests at varied Toronto coordinates.', bold: ['1.21 km', '30', '400'] },
    ],
    methodologyOrdered: true,
    methodology: [
      { text: "Sampled live shadow-call to Geoapify's Route Matrix API at a 10% rate, dispatched as a fire-and-forget background task after the response is already sent, never on the request's critical path.", bold: ['10%'] },
      { text: '400 triage requests fired via a ThreadPoolExecutor-based Python script against 12 scattered Toronto coordinates and eval test accounts — not a load-testing tool, request-volume for sample diversity, not throughput stress testing.', bold: ['400'] },
      { text: '30 real Geoapify comparisons observed via the routing_shadow_error_km Prometheus summary metric (mean = sum/count, read directly off /metrics — no log scraping). Window: 2026-07-14, eval Supabase project.', bold: ['30', '2026-07-14'] },
    ],
  },
  {
    slug: 'two-tier-facility-state-cache-redis-wait-times',
    navSection: 'infrastructure',
    category: 'Realtime Load Tracker',
    accent: 'mint',
    icon: ChartLineUp,
    tags: ['#Caching', '#Redis', '#Resilience'],
    title: 'Two-Tier Facility State: In-Process Cache + Redis Wait Times',
    readTimeMinutes: 8,
    publishedDate: '2026-05-24',
    updatedDate: '2026-07-14',
    author: 'MediCoord Core Platform Team',
    summary:
      'Splitting facility state into two tiers that match their actual freshness and failure requirements: an in-process ETag cache for the rarely-changing facility directory, and a Redis cache-aside chain with a Supabase fallback for wait times that change every scrape cycle.',
    background:
      'Two very different pieces of facility data feed every triage decision: the facility directory itself (name, address, accepted severities, changes rarely) and current ER wait times (changes every scrape cycle). They have different freshness requirements, different failure tolerances, and, in the current implementation, genuinely different storage.',
    problem:
      "Wait-time data goes stale fast and comes from unreliable external sources: a scheduled worker scrapes multiple public ER-wait sites every ~15 minutes, and any one of those sources, or Redis itself, can be down at read time. A routing decision can't just fail because a third-party wait-time site timed out; it has to degrade to something reasonable. Meanwhile the facility directory needs to survive being read on every single triage request without a database round trip each time, but a plain in-process cache doesn't survive a redeploy or a second server instance, which is a real limitation, not a hypothetical one.",
    problemHighlights: [
      {
        heading: 'External Sources Fail Silently',
        body: 'Wait-time scrapers hit third-party sites that can go down, change their markup, or return stale numbers with no warning. The read path has to assume any single source can fail on any given request.',
        accent: 'danger',
      },
      {
        heading: "In-Process Cache Doesn't Scale Out",
        body: "The facility directory cache lives in a single Python process's memory. It's fast, but it's also gone on restart and invisible to a second server instance. There's no cross-process consistency today.",
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: 'One cache for everything, in Redis',
        body: "Putting the facility directory in Redis too, alongside wait times, would remove the single-process limitation immediately. We didn't do that yet because the facility directory changes at a completely different rate than wait times: it's edited by hand or by an admin process, not scraped every 15 minutes. Adding a network hop to read data on every single triage request for something that rarely changes is the wrong trade when a single-process deployment is what's actually running today.",
      },
      {
        title: 'Fail closed on scraper/Redis errors',
        body: 'The tempting alternative to degrading to an empty wait-time map is to raise and block the routing decision until wait data is available. We rejected that because a routing decision without wait-time data is still strictly better than no routing decision at all. The same reasoning already applied to the facility hours filters, extended here for consistency rather than inventing a new failure convention for this one data source.',
      },
    ],
    approach:
      "We split facility state into two tiers that match their actual freshness and failure requirements. The facility directory lives as a module-level dict, populated from a Supabase query and stamped with a SHA-256 ETag over its sorted-key JSON serialization, cheap to read on every request, and the ETag lets callers detect 'nothing changed' without re-fetching. Wait times go through a proper cache-aside chain: read the Redis hash first, since that's what the scraper writes every ~15 minutes; on a Redis error or an empty hash (cold start, before the first scrape has ever run), fall back to a Supabase RPC and best-effort repopulate Redis from that result via a pipeline write, so the next read doesn't have to hit Supabase again. If both Redis and the Supabase fallback fail, the function returns an empty map rather than raising. Missing wait data is treated the same way missing hours data is treated elsewhere in the codebase: it always passes filters rather than blocking a routing decision.",
    approachEmphasis: ['cache-aside chain', 'always passes filters rather than blocking a routing decision'],
    codeSamples: [
      {
        filename: 'cache.py',
        language: 'python',
        content: `_cache: dict[str, Any] = {"facilities": None, "etag": None}

def get_cached_facilities() -> tuple[list[dict] | None, str | None]:
    return _cache["facilities"], _cache["etag"]

def set_cached_facilities(data: list[dict]) -> str:
    serialized = json.dumps(data, sort_keys=True, default=str)
    etag = f'"{hashlib.sha256(serialized.encode()).hexdigest()[:32]}"'
    _cache["facilities"] = data
    _cache["etag"] = etag
    return etag`,
      },
      {
        filename: 'wait_times.py',
        language: 'python',
        content: `def get_wait_minutes_map() -> dict[str, int | None]:
    try:
        raw = redis_client.hgetall(REDIS_HASH_KEY)
        if raw:
            return {fid: json.loads(v).get("wait_minutes") for fid, v in raw.items()}
    except Exception:
        logger.warning("redis_unavailable_falling_back_to_supabase")

    try:
        rows = supabase_rpc("latest_wait_times", {})
    except Exception:
        logger.warning("wait_times_fallback_failed_returning_empty")
        return {}

    wait_map = {r["facility_id"]: r["wait_minutes"] for r in rows}
    try:
        pipe = redis_client.pipeline()
        for r in rows:
            pipe.hset(REDIS_HASH_KEY, r["facility_id"], json.dumps({
                "wait_minutes": r["wait_minutes"], "raw_wait": r.get("raw_wait"),
            }))
        pipe.execute()
    except Exception:
        logger.warning("redis_populate_failed")

    return wait_map`,
      },
    ],
    diagramSteps: [
      { title: 'Facility Directory Read', desc: 'In-process dict, ETag over sorted-key JSON. No per-request Supabase query.', icon: 'ti ti-database' },
      { title: 'Wait-Time Cache-Aside Read', desc: 'Redis hash wait_times:current checked first, written by the scraper every ~15 min.', icon: 'ti ti-refresh' },
      { title: 'Supabase Fallback', desc: 'On Redis miss or error, latest_wait_times RPC runs and best-effort repopulates Redis.', icon: 'ti ti-arrow-back-up' },
      { title: 'Graceful Degradation', desc: 'If both fail, return an empty map. Missing wait data always passes filters.', icon: 'ti ti-shield-check' },
    ],
    diagramImage: {
      src: twoTierCacheDiagram,
      alt: 'Diagram of the two-tier state read path: in-process facility cache, Redis wait-time cache-aside read, Supabase fallback, and graceful degradation to an empty map',
      caption: 'FIG 3.1: TWO-TIER STATE READ PATH',
    },
    lessonsLearned: [
      {
        title: 'The Redis repopulate-on-fallback step needs its own try/except',
        body: 'The first version of the Supabase fallback path let a Redis write failure during the best-effort repopulate step propagate up and mask a successful Supabase read. The caller would see an error even though it actually had good wait-time data in hand. Wrapping just that pipeline write in its own try/except, separate from the read path exception handling, fixed it.',
      },
      {
        title: 'ETag comparison beats re-diffing the facility list',
        body: 'Early versions of the facility cache had no ETag and downstream consumers re-serialized the full list on every poll to check whether anything had changed. Hashing the sorted-key JSON once at write time and comparing that string is far cheaper than re-diffing a list of facility dicts.',
      },
    ],
    tradeoff:
      "The facility-directory cache is explicitly a Phase 1 shortcut: it works for single-node deployment but doesn't survive horizontal scaling or process restarts. Every server instance would build its own independent view of the facility directory, with no invalidation signal between them. Wait times don't have that problem since Redis is already the shared store, but the two-tier split means the two data types have genuinely different consistency guarantees today, which is worth knowing if you're debugging why one field updated instantly and another didn't. What's next: moving the facility directory into the same shared store as wait times (Redis Cluster with AOF persistence) is the change that would let this run on more than one process. Priority-queue gating (routing emergent cases first, letting moderate/routine absorb remaining capacity) is also not backend logic yet; today that coordination is what Sandbox Mode visualizes on the frontend, not something this cache enforces server-side.",
    result: [
      { text: '100% cache hit rate across 300 wait-time reads (300 redis_hit, 0 supabase_fallback) under a sustained read burst.', bold: ['100%', '300'] },
      { text: 'Cache-aside mechanism confirmed correct end-to-end in an earlier verification pass: 1st read after a cold Redis hash triggered supabase_fallback and repopulated Redis, 2nd read correctly hit redis_hit.', bold: ['1st', '2nd'] },
    ],
    methodologyOrdered: true,
    methodology: [
      { text: 'wait_times_cache_outcome_total: a Prometheus counter labeled by outcome (redis_hit, supabase_fallback, total_failure), incremented on the existing cache-aside branches inside get_wait_minutes_map(). Zero added latency, no new endpoint.', bold: [] },
      { text: '300 unauthenticated GET /facilities requests fired via a ThreadPoolExecutor-based Python script against the eval-project preview backend — not a load-testing tool, same approach as case study 2.', bold: ['300'] },
      { text: 'Hit rate computed by diffing wait_times_cache_outcome_total before and after the burst, read directly off /metrics. Window: 2026-07-14, eval Supabase project.', bold: ['2026-07-14'] },
    ],
  },
  {
    slug: 'event-driven-fan-out-eventbridge-serverless-pipeline',
    navSection: 'infrastructure',
    category: 'Serverless Pipeline Orchestration',
    accent: 'blue',
    icon: FlowArrow,
    tags: ['#AWS', '#IaC', '#EventBridge', '#Serverless'],
    title: 'Event-Driven Fan-Out: S3 to Lambda to EventBridge to dbt',
    readTimeMinutes: 7,
    publishedDate: '2026-06-16',
    updatedDate: '2026-07-14',
    author: 'MediCoord Core Platform Team',
    summary:
      'Decoupling a multi-source ingestion pipeline into independent Lambda stages using native S3 and EventBridge event triggers instead of a Step Functions orchestrator or a polling coordinator — so a failure in one processor never blocks the others, and a completion signal from any of three independent sources fans into one shared transform-integrity-test-live-health checkpoint.',
    background:
      "Three independent external sources (Places, ER-wait, Open Data) each need fetch, S3 landing, process/upsert, and shared dbt transformation before the data is usable for triage routing. Coordinating three sources that get added, disabled, or moved independently over time (ER-wait was later moved to a Railway worker, Sprint 12) is a different problem than coordinating a single fixed pipeline.",
    problem:
      "A central orchestrator has to know about every source up front — adding or retiring a source means editing shared orchestration state, not just adding or removing an independent resource. And a failure in one source's processor shouldn't block or freeze the sources that are healthy.",
    problemHighlights: [
      {
        heading: 'Central Orchestrator = Central Coupling',
        body: "A Step Functions state machine (or any central coordinator) has to know about every source up front; adding a 4th source means editing the orchestrator's definition, not just adding an independent stack resource.",
        accent: 'danger',
      },
      {
        heading: "One Failure Shouldn't Freeze the Rest",
        body: "If one source's processor starts failing, that can't block a healthy source's processor from running or the shared dbt-runner from firing on the sources that did succeed.",
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: 'Step Functions state machine',
        body: "Its centralized definition doesn't match how sources actually get added or retired over time (ad hoc, sometimes disabled entirely, as ER-wait was). Editing a state machine to add or remove a branch is more coupling than the problem needs.",
      },
      {
        title: 'Polling/cron-based coordinator',
        body: 'A periodic Lambda or status-table poll adds latency and a dedicated moving part solely for coordination that S3/EventBridge already provides natively, at no extra cost.',
      },
    ],
    approach:
      "S3 Object Created events, filtered by key prefix (raw/places/, raw/er-wait/, raw/open-data/), trigger the matching processor Lambda directly — no orchestrator in between. Each processor publishes a custom ProcessorComplete event (status: SUCCESS, source medicoord.pipeline) to the default EventBridge bus after a successful Supabase upsert. One DbtRunnerRule matches that event pattern regardless of which of the three processors fired it, fanning all three into a single shared dbt-runner that never needs to know which source triggered it. Once triggered, dbt-runner runs three phases, not one: Phase 1 dbt run (transforms facilities_clean), Phase 2 dbt test (13 automated data-quality tests, 13/13 passing — an integrity gate, not just a transform), Phase 3 the medi_db_health_check Supabase RPC (dead tuples, long-running queries, deadlocks — a live database health check, not a pipeline-internal check). IAM backs the whole chain with three least-privilege roles: ingestion (SSM read + S3 write + logs), processor (S3 read + logs + EventBridge publish scoped to the default bus), dbt-runner (logs only — Supabase access is HTTPS with env-injected credentials, no AWS resource access needed). The pipeline is defined across two separate CloudFormation stacks, not one. s3-buckets.yaml (plain CloudFormation) defines the landing bucket with native EventBridgeConfiguration (S3-to-EventBridge without the manual console toggle that was tried first and abandoned), a 30-day lifecycle expiry (raw files are transient — cost hygiene, not an afterthought), and a full PublicAccessBlockConfiguration (this bucket is internal-only, stated explicitly rather than left to default). template.yaml (AWS SAM) defines the compute layer: 3 IAM roles, 4 processing/ingestion Lambdas plus dbt-runner, EventBridge rules. The S3 stack exports BucketName/BucketArn via CloudFormation Export; the compute stack consumes them via !ImportValue in every IAM policy and EventBridge rule that touches the bucket — one resource, one source of truth, zero hardcoded ARNs or duplicated bucket names across stacks.",
    approachEmphasis: ['never needs to know which source triggered it', 'one source of truth, zero hardcoded ARNs'],
    codeSamples: [
      {
        filename: 's3-buckets.yaml',
        language: 'yaml',
        content: `Outputs:
  BucketName:
    Description: Name of the raw ingestion bucket
    Value: !Ref MedicoordRawBucket
    Export:
      Name: medicoord-ingestion-bucket-name

  BucketArn:
    Description: ARN of the raw ingestion bucket
    Value: !GetAtt MedicoordRawBucket.Arn
    Export:
      Name: medicoord-ingestion-bucket-arn`,
      },
      {
        filename: 'template.yaml',
        language: 'yaml',
        content: `# One rule covers all three processors — fires when any processor
# publishes ProcessorComplete with status SUCCESS. dbt-runner never
# knows which source triggered it.
DbtRunnerRule:
  Type: AWS::Events::Rule
  Properties:
    Name: medicoord-dbt-runner-rule
    EventPattern:
      source:
        - medicoord.pipeline
      detail-type:
        - ProcessorComplete
      detail:
        status:
          - SUCCESS
    State: ENABLED
    Targets:
      - Id: DbtRunnerTarget
        Arn: !GetAtt DbtRunner.Arn

# Cross-stack reference — no hardcoded bucket ARN
S3Write:
  PolicyDocument:
    Statement:
      - Effect: Allow
        Action: s3:PutObject
        Resource: !Sub
          - '\${BucketArn}/*'
          - BucketArn: !ImportValue medicoord-ingestion-bucket-arn`,
      },
      {
        filename: 'dbt-runner/handler.py',
        language: 'python',
        content: `logger.info("Phase 1 — dbt run")
# ... run facilities_clean transform ...

logger.info("Phase 2 — dbt test")
# ... 13 automated data-quality tests, fails loudly on bad data ...

logger.info("Phase 3 — DB health checks (RPC)")
# ... medi_db_health_check: dead tuples, long-running queries, deadlocks ...`,
      },
    ],
    diagramSteps: [
      { title: 'Scheduled Ingestion', desc: 'An EventBridge Schedule rule fires an ingestion Lambda on a 7-day cadence, writes raw JSON to S3 under a source-specific prefix.', icon: 'ti ti-clock' },
      { title: 'S3 Event Trigger', desc: 'S3 Object Created, filtered by key prefix, directly invokes the matching processor Lambda. No polling, no orchestrator.', icon: 'ti ti-cloud-upload' },
      { title: 'Processor Fan-In Signal', desc: 'After a successful Supabase upsert, the processor publishes a ProcessorComplete/SUCCESS event to the default EventBridge bus.', icon: 'ti ti-git-merge' },
      { title: 'Shared Verification Gate', desc: 'One rule matches ProcessorComplete from any of the three processors and invokes dbt-runner once: transform, then 13 data-quality tests, then a live Supabase health check.', icon: 'ti ti-shield-check' },
    ],
    diagramImage: {
      src: eventDrivenFanOutDiagram,
      alt: 'Diagram of the event-driven pipeline: scheduled ingestion writes to S3, an S3 event triggers the matching processor, the processor signals completion on EventBridge, and a shared rule fans all three sources into one dbt-runner verification gate',
      caption: 'FIG 4.1: EVENT-DRIVEN FAN-OUT PIPELINE',
    },
    lessonsLearned: [
      {
        title: 'A stale bug stayed invisible for months because nothing was watching',
        body: "places-processor 404'd on its Supabase upsert on roughly 48% of invocations (15 of 31) over a 90-day historical window, with zero downstream impact: dbt-runner kept running clean on whichever processors succeeded, and no other source was blocked. The event-driven design's resilience — failures don't cascade — is also exactly why the bug went unnoticed for so long. Decoupling contains a fault; it doesn't surface it. The fix has held for the most recent 21 days (10 invocations, 0 errors) as of this write-up.",
      },
    ],
    tradeoff:
      "Only 1 of 3 ingestion sources is actually active in this pipeline today — er-wait-scraper and open-data-sync's EventBridge Schedule rules are disabled; the team moved ER-wait ingestion to a Railway background worker instead during Sprint 12, to avoid near-real-time Lambda cost overhead. This is architecture built for three sources, one active — stated directly rather than implied by omission. Separately: because the DbtRunnerRule pattern matches ProcessorComplete from any processor, two processors completing within the same window could trigger dbt-runner twice back-to-back. Not a correctness problem — the dbt models and health-check RPC are idempotent/read-only — but worth knowing if duplicate CloudWatch log entries for dbt-runner show up close together.",
    result: [
      { text: '31 places-processor invocations over 90 days; 0 errors in the most recent 21 days (10 invocations) — a historical Supabase-upsert 404 bug is confirmed fixed.', bold: ['31', '0', '21 days', '10'] },
      { text: '12 dbt-runner invocations over 90 days, 0 errors — the shared fan-in/verification gate holds regardless of which processor triggers it.', bold: ['12', '0'] },
    ],
    methodologyOrdered: true,
    methodology: [
      { text: 'CloudWatch GetMetricStatistics (AWS/Lambda, Invocations + Errors), 90-day window, weekly buckets, per function, live production AWS account.', bold: [] },
      { text: "CloudWatch Logs filter-log-events on places-processor's log group confirmed the 404 root cause: a urllib.request.urlopen call inside upsert_facilities(), not a third-party API key issue.", bold: [] },
      { text: 'A most-recent-21-days re-check (3 weekly buckets) confirmed the fix held: 10 invocations, 0 errors.', bold: ['21-days', '10', '0'] },
    ],
  },
  {
    slug: 'two-track-llm-evaluation-groundedness-faithfulness',
    navSection: 'ai-models',
    category: 'LLM Evaluation',
    accent: 'mint',
    icon: Gauge,
    tags: ['#Evals', '#DeepEval', '#LLMAsJudge', '#RAG'],
    title: 'Two-Track LLM Evaluation: Groundedness + Faithfulness',
    readTimeMinutes: 7,
    publishedDate: '2026-07-11',
    updatedDate: '2026-07-14',
    author: 'MediCoord Core Platform Team',
    summary:
      "An LLM's output can't be verified by reading the code that calls it, so Pass 2's generator output is checked by two independent tracks, each catching a different class of unfaithfulness: a zero-cost deterministic substring check running on every live response, and an offline LLM-as-judge pass scoring subtler fabrications a string match can't see.",
    background:
      "RAG evaluation frameworks like RAGAS conventionally split into two metric families: retriever-side (context precision, context recall — did retrieval fetch the right facts) and generator-side (faithfulness, answer relevancy — given those facts, did the model's output stay true to them). MediCoord's Pass 2 architecture makes this split unusually clean: retrieval isn't a semantic/embedding search with ranking uncertainty — it's a deterministic Python lookup (find_nearest_facilities()). The correct facility is a database fact, not a probabilistic retrieval result, which collapses the retriever-eval half of that framework to a non-problem: there's no ranking or recall to score because there's nothing to rank. What's left to evaluate is purely the generator: given a fact already known to be correct, does Pass 2's LLM stay faithful to it, or does it drift, paraphrase incorrectly, or invent details the fact never contained? That's a narrower, generator-only evaluation problem than most RAG eval guides assume — and it's why this pipeline needed two tailored approaches rather than adopting a generic metric suite wholesale. RAGAS is referenced here as the conceptual vocabulary source for the retriever-vs-generator split; the actual implementation uses DeepEval's FaithfulnessMetric, not the ragas library.",
    problem:
      "Two different failure classes need two different detection strategies for that generator-only faithfulness question. A wrong facility name is a simple, exact substitution — cheap to catch deterministically. A wrong address, or a rehab centre mischaracterized as an ER, is subtler unfaithfulness a substring match can't see, but running a judge-LLM call on every live production request adds a third round-trip's cost and latency to every triage response.",
    problemHighlights: [
      {
        heading: 'Exact Substitution vs. Semantic Drift',
        body: "A wrong name is a binary, checkable fact; a wrong address or mischaracterized category requires judgment a string match can't provide.",
        accent: 'danger',
      },
      {
        heading: "Judge Calls Aren't Free",
        body: "A judge-LLM call in the live request path adds a third round-trip's worth of cost and latency to every triage response, on top of the two passes case study 1 already documents.",
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: 'LLM-as-judge on every live request',
        body: 'Rejected: cost and latency — a third LLM call in the hot path.',
      },
      {
        title: 'Deterministic-only, skip the judge entirely',
        body: 'Rejected: catches wrong names, misses wrong addresses or category mischaracterizations that still misroute a patient.',
      },
      {
        title: "Feed the full grounding-message text (with instructions) as DeepEval's retrieval_context",
        body: 'Tried and rejected: DeepEval\'s FaithfulnessMetric extracts "truths" from retrieval_context via its own LLM call; instructional text like "use this exact name" pollutes that extraction. Rebuilt as a pure factual restatement (name, address, distance only).',
      },
    ],
    approach:
      "Two tracks, matched to what each failure class actually needs — not a generic RAGAS-style metric suite applied uniformly, but a cheap deterministic check for exact-fact grounding and an LLM-as-judge pass (DeepEval's FaithfulnessMetric, the generator-side metric RAGAS's vocabulary would call faithfulness) for the subtler cases only a semantic judge can catch. Track A (online, deterministic, zero marginal cost): check_facility_groundedness() runs on every Pass-2 response — exact facility-name substring match against the deterministic lookup result, no LLM involved. Track B (offline, LLM-as-judge): 100 requests replayed through the real /chat endpoint and saved as a purpose-built transcript dataset; 89 that resolved to a facility recommendation scored offline with DeepEval's FaithfulnessMetric (gpt-4o-mini judge — chosen for cost, bounded by a stated $5-credit constraint noted in the Sprint 17 discussion notes, not claimed as the best available judge) at a 0.7 pass threshold, against build_retrieval_context()'s facts-only restatement.",
    approachEmphasis: ['zero marginal cost', 'pollute that extraction'],
    codeSamples: [
      {
        filename: 'run_faithfulness_eval.py',
        language: 'python',
        content: `def build_retrieval_context(facility: dict) -> list[str]:
    """
    Pure factual restatement — name, address, distance only.
    Deliberately NOT the full grounding-message text (which also
    contains instructions like "use this exact name"): DeepEval's
    FaithfulnessMetric extracts "truths" from retrieval_context via
    its own LLM call, and instructional text would pollute that
    extraction.
    """
    return [
        f"{facility['name']} is located at {facility['address']}, "
        f"{facility['distanceKm']} km away."
    ]


def score_transcript(transcript: dict, metric) -> dict | None:
    facility = transcript.get("recommended_facility")
    if facility is None:
        return None

    test_case = LLMTestCase(
        input=transcript["message"],
        actual_output=transcript["response_text"],
        retrieval_context=build_retrieval_context(facility),
    )
    metric.measure(test_case)
    return {
        "message": transcript["message"],
        "score": metric.score,
        "success": metric.success,
        "reason": metric.reason,
    }


def summarize_scores(results: list[dict]) -> dict:
    if not results:
        return {"count": 0, "mean_score": 0.0, "pass_rate": 0.0}
    count = len(results)
    mean_score = sum(r["score"] for r in results) / count
    pass_rate = sum(1 for r in results if r["success"]) / count
    return {"count": count, "mean_score": mean_score, "pass_rate": pass_rate}`,
      },
    ],
    diagramSteps: [
      { title: 'Live Response, Track A Gate', desc: 'Every Pass-2 response passes through check_facility_groundedness(), an exact substring match, zero LLM cost.', icon: 'ti ti-check' },
      { title: 'Offline Replay', desc: '100 requests replayed through /chat, transcripts saved as a purpose-built dataset (89 scoreable).', icon: 'ti ti-player-play' },
      { title: 'DeepEval Faithfulness Scoring', desc: 'Each transcript scored against a facts-only retrieval_context (name, address, distance) using gpt-4o-mini as judge.', icon: 'ti ti-scale' },
      { title: 'Aggregate', desc: 'Mean score and pass rate computed at a 0.7 threshold.', icon: 'ti ti-chart-bar' },
    ],
    diagramImage: {
      src: twoTrackEvalDiagram,
      alt: 'Diagram of the two-track evaluation flow: a deterministic groundedness check on every live response, an offline replay building a transcript dataset, DeepEval faithfulness scoring against a facts-only context, and score aggregation',
      caption: 'FIG 5.1: TWO-TRACK EVALUATION FLOW',
    },
    lessonsLearned: [
      {
        title: 'Retrieval-context pollution',
        body: "Feeding the judge instructional text instead of pure facts corrupts its own truth-extraction step. A lesson about the eval instrumentation itself, not the system under test: what you feed a judge model as ground truth needs the same rigor as what you feed the system being judged.",
      },
    ],
    tradeoff:
      "Track B measures faithfulness at a point in time (an offline replay), not continuously — it doesn't run on live production traffic today. Premature-classification rate (whether the model should have asked another question instead of routing) still has no ground-truth label; that's explicitly deferred to Sprint 9's prompt-evaluation work, not silently dropped from scope.",
    result: [
      { text: 'Track A — 0 hallucinated facilities across 106 grounded-response checks — 100% groundedness.', bold: ['Track A', '0', '106', '100%'] },
      { text: 'Track B — DeepEval Faithfulness score of 0.956 (96.6% pass rate at a 0.7 threshold) across 89 facility-grounded responses — catches fabricated details a name-only match cannot see.', bold: ['Track B', '0.956', '96.6%', '89'] },
      { text: 'Premature-classification rate is not yet measurable — no historical baseline exists (the abandoned single-pass prototype was never instrumented).', bold: [] },
    ],
    methodologyOrdered: true,
    methodology: [
      { text: 'Both tracks run against a dedicated staging eval environment — a separate Supabase project and preview backend seeded from real facility data, never live user traffic.', bold: [] },
      { text: 'Track A: 106 classifications had a facility present, all 106 grounded. Window: 2026-07-11, about 15 minutes, exercised via a 4-turn manual smoke test plus a 100-request single-thread synthetic conversation run.', bold: ['106', '2026-07-11', '15 minutes'] },
      { text: 'Track B: of the 100 replayed requests, 89 returned a recommended facility and were scored (the rest resolved to a clarifying follow-up question instead). Window: 2026-07-12, single-thread run against the eval Supabase project.', bold: ['89', '2026-07-12'] },
    ],
  },
  {
    slug: 'symptom-understanding-retrieval-ctas-lookup-snomed-knowledge-graph',
    navSection: 'ai-models',
    category: 'Symptom-Understanding Retrieval',
    accent: 'blue',
    icon: ShareNetwork,
    tags: ['#GraphRAG', '#Neo4j', '#SNOMEDCT', '#Evals', '#Draft'],
    title: 'Symptom-Understanding Retrieval: CTAS Lookup + SNOMED Knowledge Graph',
    readTimeMinutes: 9,
    publishedDate: '2026-08-19',
    author: 'MediCoord Core Platform Team',
    summary:
      "The tradeoff case study 1 flagged as in-progress: a knowledge-graph grounding step for the classification pass. We built a SNOMED CT knowledge graph in Neo4j behind the same GraphContextProvider interface a hand-curated CTAS lookup table already used, evaluated both with two independently-designed eval efforts, and found that the more sophisticated retrieval backend didn't retrieve better by the metrics that measure retrieval — but that turned out not to be the thing that determined the end-to-end result.",
    background:
      "A knowledge-graph retrieval idea was actually rejected once already: Sprint 15's original 'Graph RAG' proposal had no detailed scope beyond a one-line intent pointer and was scrapped for it. What replaced it was a validated two-track plan — ship a static, hand-curated lookup first, then justify a graph-based retrieval track separately and later, on its own evidence, not as a bet made in advance. Case study 1's tradeoff section named this explicitly: a knowledge-graph grounding step 'aimed at the classification step itself' was in active development, with the static two-pass orchestration as the layer it would plug into, not a replacement for it. This is that step, and the evaluation of whether it was worth building.",
    problem:
      "v1's retrieval is alias/substring matching against a manually maintained table: no embeddings, no LLM extraction, just a literal string match against a curated symptom_triage_data.json. That has two structural ceilings. First, it can't generalize to how patients actually phrase things — a match only fires if the patient's words happen to contain one of the table's exact aliases. Second, the table itself caps what the system can ever recognize: every new complaint, synonym, or red flag has to be hand-added by someone who thought to add it. A structured medical vocabulary — SNOMED CT, the terminology standard Canadian health systems already use — was the candidate fix for both ceilings at once: a vastly larger, professionally maintained concept graph instead of a hand-rolled list.",
    problemHighlights: [
      {
        heading: "Literal Matching Can't Generalize",
        body: "v1 only recognizes a symptom if the patient's words happen to contain one of a curated list of aliases verbatim — no embeddings, no semantic step, nothing that bridges lay phrasing to clinical terms.",
        accent: 'danger',
      },
      {
        heading: 'A Hand-Curated Table Has a Hard Ceiling',
        body: 'Every complaint, synonym, or red flag the system can ever recognize has to be manually authored first. The table cannot grow past what someone remembered to add.',
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: "Keep extending v1's alias table",
        body: "The lowest-effort option: keep hand-adding aliases as gaps get noticed. Rejected as a strategy, not just a tactic — it doesn't fix the structural ceiling, it just raises it slowly, and every addition is unmaintained-vocabulary debt someone has to keep paying down.",
      },
      {
        title: 'Go straight to embedding-based semantic search',
        body: "Considered and not built this round. The v2 design explicitly targeted a graph traversal with precedence rules over a curated concept set, not a vector index — a scope decision this case study's own eval later surfaces as consequential: see case study 'Fair Retrieval Evaluation' for what that specific choice cost.",
      },
    ],
    approach:
      "v1 (Sprint 18) is a straightforward Symptom → RedFlag → FollowupQuestion static lookup sourced from the CTAS (Canadian Triage and Acuity Scale) reference tables, with an explicit, reviewed mapping from CTAS's 5 acuity levels down to the app's 4-level severity schema — a deliberate design decision, not an implicit rounding. It shipped behind a feature flag with zero behavior change to existing users. v2 (Sprint 19) keeps the same GraphContextProvider interface and the same hand-curated Symptom → RedFlag → FollowupQuestion content, but re-anchors that content onto a small curated set of SNOMED CT concepts instead of hand-listed alias strings, backed by a Neo4j graph seeded from the SNOMED CT Canadian Edition (RF2 release). Severity classification stays the LLM's job unconditionally in both versions — the graph only ever supplies context, never a verdict. Getting there required a real SNOMED CT Affiliate License (submitted to SNOMED International's MLDS, approved within 3 days) plus a separate Canada Health Infoway acquisition for the Canadian Edition specifically. And the build hit a real ceiling of its own: Neo4j AuraDB's free-tier 200,000-node cap, discovered empirically mid-load at roughly 14% of the originally planned single-root subtree — not documented anywhere in advance. The fix was a redesign to a multi-root, bounded-depth (4 levels) subset keyed off the 165 CTAS complaints, landing at 31,327 concepts, 126,816 descriptions, and 50,351 IS_A relationships — 79% of the free-tier cap, with all 154 curated anchor concepts backed by loaded data, up from 69 before the redesign.",
    approachEmphasis: ['re-anchors that content onto a small curated set of SNOMED CT concepts instead of hand-listed alias strings', 'the graph only ever supplies context, never a verdict'],
    codeSamples: [
      {
        filename: 'factory.py',
        language: 'python',
        content: `def get_graph_provider() -> GraphContextProvider:
    """v1 and v2 sit behind the identical interface. Switching is an
    env var, not a code change on either side, and each provider is
    constructed once and cached, not rebuilt per request."""
    provider_name = os.environ.get("GRAPH_RAG_PROVIDER", "off").lower()
    if provider_name not in _provider_cache:
        _provider_cache[provider_name] = _build_provider(provider_name)
    return _provider_cache[provider_name]`,
      },
    ],
    diagramSteps: [
      { title: 'User Message In', desc: 'Chat turn reaches LLMAgent, same entry point regardless of which provider is active.', icon: 'ti ti-message-chatbot' },
      { title: 'Provider Selection', desc: 'get_graph_provider() reads GRAPH_RAG_PROVIDER — static, neo4j, or off — and returns a cached instance behind the shared GraphContextProvider interface.', icon: 'ti ti-git-branch' },
      { title: 'Graph Lookup', desc: 'v1: alias-substring match against the curated table. v2: SNOMED concept lookup + bounded IS_A traversal in Neo4j.', icon: 'ti ti-sitemap' },
      { title: 'Context Injected, Never a Verdict', desc: 'Matched red flags and follow-up questions are added to the LLM prompt. Severity classification stays the model\'s decision either way.', icon: 'ti ti-brain' },
    ],
    lessonsLearned: [
      {
        title: "Two eval efforts, designed independently, told two different stories",
        body: "Retrieval-quality eval (Track A/B, full depth in case study 'Fair Retrieval Evaluation') and end-to-end triage-accuracy eval (a 27-vignette multi-turn ablation) were built by different work, at different times, measuring different things. Reading either one alone would have been misleading — the pairing is the actual finding, not a footnote.",
      },
      {
        title: "This case study is the 'reasoning doc' that never got written as its own artifact",
        body: 'Sprint 19\'s original scope named a deliverable — a short write-up of why both retrieval paths exist and how the switch works — that never shipped as its own file. This case study substantially fulfills that intent; better to say so directly than leave the gap silently unresolved.',
      },
    ],
    tradeoff:
      "The production default for GRAPH_RAG_PROVIDER has not been independently confirmed against the live deployed config as of this writing — the factory code defaults to off when the env var is unset, but that's a code-level default, not a verified statement about what's actually running. Given the results below, that's worth checking rather than assuming, not a footnote. Separately, and by design: full PART_OF/cross-symptom-cluster authoring beyond one seeded pilot cluster, and expanding the entity-linking precision test suite past its current 3 pilot anchors, are both explicitly deferred to a future symptom-understanding-improvement sprint — not fixed here, and not silently dropped either.",
    result: [
      { text: 'End-to-end triage accuracy: neo4j (v2) 66.7% (18/27), off (no graph) 63.0% (17/27), static (v1) 51.9% (14/27) — v1 is the worst-performing leg of all three, including worse than no augmentation at all.', bold: ['66.7%', '63.0%', '51.9%'] },
      { text: "v1's under-triage rate (37.0%, 10/27) is the worst of the three legs and concentrated in the highest-stakes bucket: 7 of 16 emergent-severity vignettes under-triaged, versus 4 of 16 for both other legs.", bold: ['37.0%', '7 of 16', '4 of 16'] },
      { text: "Isolated retrieval quality: v1 scores 100% (20/20) hit-rate on its calibrated scenario set, v2 scores 35% (7/20) — full methodology, the vocabulary-neutral control that overturns the naive reading of this number, and the complete Track A/B tables live in case study 'Fair Retrieval Evaluation: Static Lookup vs. SNOMED Knowledge Graph'.", bold: ['100%', '35%'] },
    ],
    methodology: [
      { text: "Task 13: a purpose-built, Clean-Architecture eval harness driving 27 real Ontario CTAS vignettes through the actual multi-turn conversation agent, three legs (static / off / neo4j), scored on confusion-matrix accuracy, under-triage rate, and elicitation coverage — because the only existing vignette source is third-person exam narrative, not a chat conversation, and elicitation coverage specifically requires information that's disclosed only when asked.", bold: [] },
      { text: 'Track A/B: isolated single-turn retrieval-quality eval, run identically against both providers — see the dedicated case study for the full design, including a vocabulary-neutral control set and a stale-number correction caught mid-eval.', bold: [] },
    ],
  },
  {
    slug: 'fair-retrieval-evaluation-static-lookup-vs-snomed-knowledge-graph',
    navSection: 'ai-models',
    category: 'Retrieval Evaluation',
    accent: 'mint',
    icon: Target,
    tags: ['#RetrievalEval', '#RAG', '#DeepEval', '#Evals', '#Draft'],
    title: 'Fair Retrieval Evaluation: Static Lookup vs. SNOMED Knowledge Graph',
    readTimeMinutes: 8,
    publishedDate: '2026-08-19',
    author: 'MediCoord Core Platform Team',
    summary:
      "A retrieval comparison that looks fair on paper — same scenarios, same scoring, both providers — can still hide a confound. Building one for MediCoord's two symptom-understanding retrieval backends took a shared ranking fix, a split hit-rate/recall metric to tell coverage failures from ranking failures apart, a vocabulary-neutral control scenario set, and a caught-and-corrected stale number. The eval design process is as much the content here as the final numbers.",
    background:
      "See case study 'Symptom-Understanding Retrieval: CTAS Lookup + SNOMED Knowledge Graph' for why both retrieval backends (a static CTAS alias table, a SNOMED CT knowledge graph in Neo4j) exist and how the switch between them works. This case study starts one level down: how do you compare two retrieval systems fairly once you suspect — correctly, as it turns out — that they share their core retrieval mechanism underneath architecturally different implementations.",
    problem:
      "The first retrieval comparison run had a real, if disclosed, bias baked in: its scenario messages were written using v1's own alias vocabulary, so a system that matches on that exact vocabulary was always going to look artificially strong. Disclosing a bias in code comments isn't the same as controlling for it — nothing in the original eval separated 'v1 retrieves well' from 'v1 retrieves well on text calibrated to v1.' A second problem sat underneath the architecture docs: v1 (flat alias table) and v2 (SNOMED knowledge graph) look structurally distinct, but reading their actual query code side by side shows both retrieve via the same operation — case-insensitive substring containment — just against different vocabularies. Nothing in the design documentation surfaces that; only the code does.",
    problemHighlights: [
      {
        heading: 'A Disclosed Bias Is Not a Controlled One',
        body: "The original scenario set was written against v1's own alias vocabulary — known and commented in the code, but never isolated with an actual control set until this eval redesign.",
        accent: 'danger',
      },
      {
        heading: 'Same Mechanism, Different Vocabulary',
        body: "v1 and v2 look architecturally distinct — a flat table versus a knowledge graph — but both retrieve via literal substring containment. That equivalence only surfaces from reading the query code, not from the architecture documents.",
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: 'Score Track A as a single hit/miss number',
        body: "Rejected in favor of a split recall (was the right concept anywhere among the candidates) / hit (was it the one actually selected) metric pair. A single hit-rate number conflates two different defects — 'never found it' and 'found it, picked wrong' — that need different fixes. In practice this diagnosis mattered: v2's hit-rate and recall came back numerically identical, which is itself proof every v2 miss in that scenario set is a coverage failure, not a ranking failure.",
      },
    ],
    approach:
      "Before any comparison could be called fair, both providers needed a shared prerequisite fix: both originally used first-match-wins retrieval, so a longer, more specific match sitting later in the data could lose to an earlier, less-specific one purely by insertion order. Both were rebuilt to rank by match specificity instead. Only after that fix landed did the actual eval run: Track A is a deterministic retrieval hit-rate check, 20 isolated single-turn scenarios, identical scoring against both providers. Track B runs DeepEval's faithfulness, contextual precision, and contextual recall metrics (same judge model and methodology as case study 'Two-Track LLM Evaluation' — see that post for how those metrics work) against transcripts generated by replaying the same in-process agent used for the end-to-end eval, so no retrieval-context construction logic is duplicated between the two eval efforts. The change that actually mattered most: a second scenario set, LAY_SCENARIOS, was built specifically to avoid every one of v1's alias/name substrings — enforced programmatically against the real alias table, not by hand-checking — but it sat built and unexecuted for two weeks before this eval redesign finally ran it.",
    approachEmphasis: ['ranking by match specificity', 'sat built and unexecuted for two weeks'],
    codeSamples: [
      {
        filename: 'run_track_a_retrieval.py',
        language: 'python',
        content: `def score_hit(ctx, expected_complaint):
    """Selection accuracy: given the candidates, did the FINAL choice match?"""
    if expected_complaint is None:
        return not ctx.matched
    return ctx.matched and ctx.complaint_name == expected_complaint


def score_recall(candidates, expected_complaint):
    """Coverage: was the right concept ANYWHERE in the candidate set,
    regardless of which one got selected? Separates 'never found it'
    from 'found it, picked wrong' — collapsing these into one number
    is exactly what a naive hit-rate metric does."""
    if candidates is None:
        return None
    if expected_complaint is None:
        return len(candidates) == 0
    return expected_complaint in candidates`,
      },
    ],
    diagramSteps: [
      { title: 'Shared Ranking Fix', desc: 'Both providers rebuilt to rank matches by specificity instead of first-match-wins, a precondition for any fair comparison.', icon: 'ti ti-adjustments' },
      { title: 'Track A — Hit-Rate + Recall', desc: '20 isolated scenarios, both providers, split into selection accuracy (score_hit) and coverage (score_recall).', icon: 'ti ti-target-arrow' },
      { title: 'Track B — DeepEval Faithfulness', desc: 'Transcripts generated via the real in-process agent, scored for faithfulness, contextual precision, contextual recall.', icon: 'ti ti-scale' },
      { title: 'Vocabulary-Neutral Control', desc: 'LAY_SCENARIOS, built to avoid every v1 alias substring, run for the first time — the result that overturned the headline number.', icon: 'ti ti-flask' },
    ],
    lessonsLearned: [
      {
        title: 'A disclosed bias needs an actual control, and the control has to actually run',
        body: "Naming a bias in a code comment doesn't neutralize it. LAY_SCENARIOS existed, tested, and ready for two weeks before it was finally executed — eval debt accumulates exactly like code debt, silently, until someone runs the thing that was already built.",
      },
      {
        title: 'A stale number shipped everywhere it was quoted',
        body: "The original v2 hit-rate figure (8/20, 40%) predated the shared ranking fix above and was never re-run afterward — it propagated into every downstream summary and an already-published write-up before the re-run caught it. The corrected number is 7/20 (35%), and the ranking fix turned out to change nothing here: recall and hit-rate came back identical, meaning every miss was a coverage failure the fix had no way to touch.",
      },
    ],
    tradeoff:
      "This eval measures isolated single-turn retrieval quality. It says nothing on its own about end-to-end triage outcome — see case study 'Symptom-Understanding Retrieval' for that separate, complementary result, where the system with the worse retrieval score wins on the metric that matters. Track B's v2 numbers were generated before this eval's Track A re-run and have not themselves been independently re-verified against the same ranking-fix code path; the ranking fix should only affect which candidate wins when multiple match, not whether DeepEval scores the resulting context as faithful, but that's an inference, not a re-run result, and is stated here as an open item rather than a settled one.",
    resultOrdered: false,
    result: [
      { text: 'Corrected: v2 (neo4j) Track A hit-rate is 35% (7/20), not the 40% (8/20) previously quoted — the original figure was stale, predating the shared ranking fix. v1 (static) scores 100% (20/20) on the same scenario set.', bold: ['35%', '40%', '100%'] },
      { text: "v2's recall is also 35% — numerically identical to its hit-rate, proving every miss is a coverage failure (the concept was never among the candidates), not a selection/ranking failure.", bold: ['35%'] },
      { text: 'Vocabulary-neutral control (LAY_SCENARIOS, n=10, run for the first time): both v1 and v2 score 0% (0/10). Neither system does semantic retrieval — both match via literal substring containment, just against different vocabularies. v1\'s 100% on the main set is a vocabulary-overlap artifact, not evidence of a better retrieval mechanism.', bold: ['0%', '0/10'] },
      { text: 'Track B (DeepEval): faithfulness 96.2% (v1) vs. 100% (v2); contextual precision 89.6% (v1) vs. 33.7% (v2); contextual recall 100% (v1) vs. 33.3% (v2) — v1 wins every axis except faithfulness, where both sit near ceiling.', bold: ['96.2%', '100%', '89.6%', '33.7%', '33.3%'] },
    ],
    methodologyOrdered: true,
    methodology: [
      { text: 'Track A and Track B both run against the same 20-scenario main set, both providers, identical scoring code — no per-provider special-casing.', bold: [] },
      { text: "Track B's judge model is gpt-4o-mini, the same model and methodology as case study 'Two-Track LLM Evaluation' — see that post for how faithfulness/contextual precision/recall are computed; not re-explained here.", bold: [] },
      { text: 'LAY_SCENARIOS: 10 vocabulary-neutral scenarios, verified programmatically to contain zero substring overlap with v1\'s real alias table before being trusted as a control.', bold: ['10'] },
      { text: "Explicitly not re-run: Track B's v2 numbers predate the ranking fix validated by the Track A re-run above and have not been independently re-verified against it — stated directly rather than silently assumed unaffected.", bold: [] },
    ],
  },
  {
    slug: 'semantic-retrieval-graph-v3-vs-no-graph-baseline',
    navSection: 'ai-models',
    category: 'Symptom-Understanding Evaluation',
    accent: 'blue',
    icon: ChartLineUp,
    tags: ['#SemanticSearch', '#Embeddings', '#ONNX', '#Evals', '#NegativeResult'],
    title: 'Semantic Retrieval Fixed the Lookup, Not the Triage: Graph v3 Against a No-Graph Baseline',
    readTimeMinutes: 10,
    publishedDate: '2026-11-13',
    author: 'MediCoord Core Platform Team',
    summary:
      "The August evaluation ended on one finding: neither retrieval backend did semantic matching, so both scored 0/10 on lay language. Graph v3 adds an embedding step to the graph and lifts retrieval from 4% to 83–93% hit@5 on lay messages. Measured end to end under a stricter, paired evaluation, it did not make triage safer: v3 under-triaged 29.6% of lay-language conversations against 22.2% with no graph at all. Production stays on the no-graph path, and this post publishes the negative result.",
    background:
      "Case study 'Symptom-Understanding Retrieval: CTAS Lookup + SNOMED Knowledge Graph' explains why a graph grounding step exists and how the GRAPH_RAG_PROVIDER switch works. Case study 'Fair Retrieval Evaluation' showed that both the static lookup (v1) and the SNOMED graph (v2) retrieve by literal substring containment, and both scored 0/10 on a vocabulary-neutral control set. Two things changed since then. The v2 graph was deleted when its free hosting tier paused, so its August numbers are kept for reference only. And the August posts left an open question: wording was proven to drive retrieval, but whether it also drives end-to-end triage had never been measured. This post answers that question and tests the fix.",
    problem:
      "Patients describe symptoms in their own words: 'my chest feels tight and heavy', not 'chest pain, cardiac features'. A lookup built on substring matching only fires when the patient happens to use the table's wording; on 150 author-written lay messages it found the right complaint 4% of the time. The August evaluation could not settle whether that mattered for triage either. It was one run of 27 conversations per leg, with no confidence intervals, on the original exam-style wording only, so a three-point gap between legs could have been noise. Fixing retrieval without first fixing the measurement would have produced a number nobody could trust.",
    problemHighlights: [
      {
        heading: 'Substring Matching Misses How Patients Talk',
        body: 'On 150 author-written lay messages, the substring lookup found the right complaint 4% of the time. Lay phrasing rarely contains the clinical term verbatim.',
        accent: 'danger',
      },
      {
        heading: 'The August Eval Could Not Separate Signal From Noise',
        body: 'One run, 27 conversations per leg, no intervals, original wording only. Later we measured that identical re-runs move a leg by about 5 points, larger than most of the August gaps.',
        accent: 'info',
      },
    ],
    alternativesConsidered: [
      {
        title: "Keep extending the alias table with lay phrases",
        body: 'Tested directly: adding 1,487 generated lay phrases to the substring lookup roughly doubled its hit rate, to about 10–17%. Verbatim matching is the ceiling, not the vocabulary size.',
      },
      {
        title: 'pgvector in the application database',
        body: 'Deferred. The index is about 30–60 MB of vectors over a few thousand target strings, small enough to hold in the API process as one matrix. A database round trip on every chat turn buys nothing at that size.',
      },
      {
        title: 'SapBERT, as the design brief recommended',
        body: 'Measured before choosing. On lay sentences SapBERT and S-PubMedBert-MS-MARCO reached roughly 50–75% hit@5, below both BioLORD-2023 and bge-small. Models trained to align clinical synonyms do not automatically handle everyday phrasing.',
      },
      {
        title: 'Index the full SNOMED subtree under each complaint',
        body: 'Rejected after measuring it. Adding descendants down to depth 2 lowered hit rates for every model: complaints with thousands of descendant terms win by volume (a hub effect). v3 indexes depth 1 by default and depth 0 for catch-all complaints.',
      },
    ],
    approach:
      "The work had two halves, done in this order. First, freeze the evaluation. We wrote a lay-language version of the 27 clinician-reviewed vignettes: same case, same gold severity, everyday wording, each line checked clinically, and frozen before v3 was designed so it could not be written in v3's vocabulary. Each vignette runs 3 times per leg (81 conversations), legs are compared pairwise with McNemar's exact test and a paired bootstrap, and a run manifest pins the model, temperatures, prompt hashes and checklist hash so a resumed run cannot silently change conditions. The line in the sand was written before any paid run: if v3 does not beat the no-graph leg beyond the paired interval on the lay set, the no-graph path stays the production default and the negative result is published. Second, build v3. The graph was rebuilt small and bounded around the 154 curated complaint anchors, with a reviewed lay-description layer stored next to the SNOMED terms. A semantic candidate path embeds the current message with an ONNX int8 model, searches an in-process vector index, and abstains when the best complaint is not clearly ahead. The existing lexical lookup stays: a long exact match still outranks any semantic hit, and if the embedder is slow or failing, a deadline, a circuit breaker and a bounded queue drop the turn back to lexical-only. Severity stays the LLM's decision in every leg; the graph only supplies context.",
    approachEmphasis: ['The line in the sand was written before any paid run', 'abstains when the best complaint is not clearly ahead'],
    codeSamples: [
      {
        filename: 'semantic_provider.py',
        language: 'python',
        content: `# Lexical pass — always runs.
lexical = super()._gather_candidates(user_message, all_text)

# Re-weight lexical hits: long = strong, short = weak evidence.
scores: dict[str, float] = {}
for concept_id, length in lexical.items():
    if length >= LEXICAL_PRECEDENCE_MIN_LEN:
        scores[concept_id] = 1000.0 + length
    else:
        scores[concept_id] = length / 1000.0

# Semantic pass — query with the CURRENT message only.
result: CandidateResult = source.candidates(user_message)
if result.skipped is None and result.candidates:
    sem_scores = anchor_scores(result.candidates)
    decision = decide(sem_scores, settings.score_threshold, settings.gap_margin)`,
      },
      {
        filename: 'abstention.py',
        language: 'python',
        content: `def decide(scores: Mapping[str, float], threshold: float, margin: float) -> Decision:
    """Semantic search always returns *something*. Accept the top complaint
    only if it is close enough AND clearly ahead of the runner-up."""
    if not scores:
        return Decision(False, "no_candidates")
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < threshold:
        return Decision(False, "low_score")
    if len(ranked) > 1 and ranked[0] - ranked[1] < margin:
        return Decision(False, "small_gap")
    return Decision(True, "ok")`,
      },
    ],
    diagramSteps: [
      { title: 'Message In', desc: 'The current chat message reaches the provider. History is never passed to the embedder.', icon: 'ti ti-message-chatbot' },
      { title: 'Lexical Pass', desc: 'Substring lookup against SNOMED and alias terms. A long exact match outranks anything semantic.', icon: 'ti ti-text-recognition' },
      { title: 'Semantic Pass', desc: 'ONNX int8 embedding, in-process vector search, abstain on a low score or a small gap. Deadline, breaker and bounded queue fall back to lexical-only.', icon: 'ti ti-vector' },
      { title: 'Context, Never a Verdict', desc: 'Matched red flags and follow-up questions go into the prompt. The LLM still decides severity.', icon: 'ti ti-brain' },
    ],
    lessonsLearned: [
      {
        title: 'A retrieval metric is not an outcome metric',
        body: 'Retrieval hit@5 went from 4% to 83–93% on lay messages. Under-triage did not improve, and accuracy dropped by about 5 points. Finding the right complaint and asking the right questions about it are different problems; v3 solved the first.',
      },
      {
        title: 'Measure your noise floor before reading a gap',
        body: 'A replay of the same lay set with identical settings moved the no-graph leg by 5 points. Most of the August gaps between legs were smaller than that. Repeats and paired intervals are what turned this into a result instead of an anecdote.',
      },
      {
        title: 'Writing the decision rule first made the negative result easy to publish',
        body: 'Because the line in the sand existed before the paid run, there was nothing to argue about when v3 lost: production stays on the no-graph path, and the write-up says so.',
      },
      {
        title: 'Trust the model ranking more than the absolute levels',
        body: 'The retrieval queries are synthetic (author-written, or LLM-written and then filtered by a blind labeler). BioLORD over bge-small over SapBERT held on every set; the exact percentages are likely optimistic for real guest messages.',
      },
    ],
    tradeoff:
      "Keeping the no-graph path as the default is not free. Without a graph doing part of the understanding, every guest's symptom text goes to the hosted model, and there is no data processing agreement with the model host yet. Matching the no-graph leg on safety and on the questions asked is the condition for moving part of that work off the model, and v3 does not meet it today. v3 is built and measured, off in production. Between the two embedding models there is a second tradeoff: bge-small embeds a message in about 3 ms with about 115 MB of memory and a 34 MB model file, the realistic choice on a 1 vCPU box, but misses the 75% hit@5 screen on all four query sets. BioLORD-2023 passes the screen but takes 19–31 ms, about 600 MB of memory and a 418 MB file, and needs SNOMED/UMLS licence compliance. Open questions: whether the model host matters (the August runs used Groq, these used Ollama Cloud, and no host check was run), and why v3 misses the vignettes it misses. An early, unquantified reading is that generic red flags plus a patient's 'no' answers get treated as reassurance and pull severity down.",
    resultOrdered: false,
    result: [
      { text: 'Retrieval, BioLORD-2023: gold complaint in the top 5 for 92.7%, 87.7%, 82.7% and 84.4% of messages on four query sets of 104 to 365 messages (top 1: 70.7%, 54.5%, 37.5%, 49.3%). Only the top 5 is reliable.', bold: ['92.7%', '82.7%'] },
      { text: 'Retrieval, bge-small: 69 to 81% top 5 (36 to 56% top 1) on the same sets, below the 75% screen on all four. Substring matching scored 4% on the 150 author-written messages.', bold: ['69 to 81%', '4%'] },
      { text: 'Under-triage, lay wording, 81 conversations per leg: no graph 22.2%, static lookup 27.2%, v3 29.6%. Accuracy: 69.1%, 64.2%, 64.2%.', bold: ['22.2%', '27.2%', '29.6%'] },
      { text: 'Under-triage, original wording: no graph 23.5%, static lookup 25.9%, v3 28.4% (accuracy 69.1%, 66.7%, 65.4%). August, one run on original wording: no graph 22.2%, static 37.0%, v2 22.2%.', bold: ['23.5%', '25.9%', '28.4%'] },
      { text: 'Paired v3 minus no graph on the lay set: 7.4 points more under-triage, 95% interval [−14.8, −1.2] on the paired difference, exact McNemar p = 0.25. No evidence the graph helps, not proof it harms.', bold: ['7.4 points', 'p = 0.25'] },
      { text: 'Replay of the lay set with identical settings: 27.2%, 30.9%, 32.1%. The no-graph leg moved 5 points between identical runs, so smaller gaps are noise.', bold: ['5 points'] },
      { text: 'Elicitation coverage (share of patient-answerable checklist facts the chat drew out): no graph 35.5%, static 33.9%, v3 32.6%; v3 minus no graph −2.9 points [−11.7, +3.1]. The graph does not get the chat to ask for more of what a clinician needs.', bold: ['35.5%', '32.6%'] },
      { text: 'Decision: v3 does not beat the no-graph leg beyond the paired interval, so the no-graph path stays the production default.', bold: ['stays the production default'] },
    ],
    methodologyOrdered: true,
    methodology: [
      { text: '27 clinician-reviewed Ontario CTAS vignettes in two wordings (original and lay), 3 repeats each: 81 conversations per leg per wording. Legs: no graph, static lookup, v3.', bold: ['81 conversations'] },
      { text: 'System under test: gpt-oss-120b on Ollama Cloud. Simulated patient: claude-haiku-4-5. Severity and under-triage are scored in code against the gold label; LLM judges were off for the paid run.', bold: [] },
      { text: 'Paired comparison on shared vignettes: McNemar exact test on per-vignette under-triage and a paired bootstrap interval on the rate difference. A run manifest pins model, temperatures, prompt hashes and checklist hash, and is enforced on resume.', bold: [] },
      { text: 'Retrieval: 154 complaint anchors; four query sets of 104 to 365 messages, author-written or LLM-written with the complaint name hidden and kept only if a blind labeler agreed. Synthetic, not real guest messages.', bold: [] },
      { text: 'Elicitation coverage was scored afterwards on the saved lay conversations by gpt-4o-mini. The second-judge agreement check was misconfigured, so judge reliability is unproven. About $0.70 spent on judging.', bold: [] },
      { text: 'Not run: a check on the original Groq host, and the live provider fallback chain. One full run plus one replay of the lay set; no further repeats.', bold: [] },
    ],
  },
]
