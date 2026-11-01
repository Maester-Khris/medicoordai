# Load tests (k6)

Run through the official k6 image; nothing is installed on the host. Run from the repository
root. Results go to `artifacts/perf/` (git-ignored).

```bash
mkdir -p artifacts/perf

# Test A, non-LLM. SCENARIO: smoke | average | breakpoint | soak
docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -e BASE_URL=https://<api-under-test> -e INTERNAL_TOKEN="$DEMO_INTERNAL_TOKEN" -e SCENARIO=smoke \
  -v "$PWD/backend/scripts/load:/scripts:ro" -v "$PWD/artifacts/perf:/out" \
  grafana/k6 run /scripts/test_a.js --summary-export /out/test-a-smoke.json

# Test B, chat. Against a real provider it spends LLM quota on every turn: keep the steps low.
docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -e BASE_URL=https://<api-under-test> -e INTERNAL_TOKEN="$DEMO_INTERNAL_TOKEN" -e STEPS=1,2,5,10,20,40 \
  -v "$PWD/backend/scripts/load:/scripts:ro" -v "$PWD/artifacts/perf:/out" \
  grafana/k6 run /scripts/test_b.js --summary-export /out/test-b.json
```

Test B holds conversations of 2 to 3 turns (`TURNS_MIN`, `TURNS_MAX`), one fresh guest each, with
origins spread over the city. Without `STEPS` it climbs 40, 100, 250, 500, 1,000, 1,500, 2,000
conversations at once, which is only meant for a target that uses the mock below. A busy answer
(429) is counted in `chat_turn_busy`, apart from `chat_turn_failed`. The run stops itself when
turn p95 passes 15 s or failures pass 5%.

Test A sends `If-None-Match` on half of its facility-list requests; `not_modified_304` counts
the 304 answers.

Before a run against a deployed API:

- Never point these at the public demo service. The target is the staging service.
- Raise `RATE_LIMIT_CHAT_IP` and `RATE_LIMIT_ROUTES_IP` on the target: every request comes from
  one IP, and with the defaults the test measures the limiter after 30 chat turns.
- Set `DEMO_INTERNAL_TOKEN` on the target and pass the same value as `INTERNAL_TOKEN`, so the
  guests the test creates are marked internal and can be deleted afterwards
  (`delete from guests where is_internal`; the other tables follow by cascade).
- Set `ROUTING_SHADOW_SAMPLE_RATE=0` on the target for Test B: the shadow comparison makes an
  extra Geoapify call on a share of chat turns.
- `MEMORY_PROFILE` must be off on the target for any run whose numbers are reported: tracing
  slows the process.

`POST /routes` is capped at 2 requests per second in every Test A scenario because each request
makes three calls on the metered Geoapify key. Transit is not exercised under load.

## The provider mock

`mock_provider.py` stands in for Groq chat completions and Geoapify routing, so a chat test can
go to thousands of turns without spending quota. It answers with the shape of the real replies
after a delay drawn from a distribution (defaults: LLM mean 2.2 s, routing p50 1.0 s and
p95 1.9 s, as measured in Sprint 21). Its settings are listed at the top of the file.

```bash
cd backend && uvicorn scripts.load.mock_provider:app --port 8080
curl -s localhost:8080/stats            # what the API sent: calls per provider, peak in flight
curl -s -X POST localhost:8080/stats/reset
```

Point an API at it with `GROQ_BASE_URL` and `GEOAPIFY_BASE_URL` (the address of the mock, no
path). Set them on the staging Railway service only, never in Doppler `stg`, which feeds the
public demo. `/health` on the API then reports `"stubbed": true`.

On Railway the mock is its own service, built from `backend/` with "Config file path" set to
`/backend/railway.mock.toml`. That file is not named `railway.toml` on purpose: every service
rooted in `backend/` would read it and start the mock instead of the API.

## Horizontal scaling, locally (Docker Compose)

`compose/` holds a local stack: nginx in front of N API replicas (1 CPU and 768 MB each), Redis
and the mock. Nothing in it reaches Railway, the real providers or Doppler. The database is the
existing local container `medicoord-demo-pg` (`migrations/postgres/README.md`), which the script
attaches to the stack's network; it must hold facilities and wait times.

```bash
source /home/niki/Documents/workenv/pydev/bin/activate
python backend/scripts/load/compose/run_horizontal.py     # about 20 minutes
```

At 1, 2 and 4 replicas it checks that:

1. throughput at the bend of the latency curve grows with the replicas;
2. a conversation whose turns land on different replicas keeps its history;
3. the load counters summed in Redis equal the recommendations made, one field per replica;
4. stopping one replica mid-run leaves the others serving.

The result is a ratio between replica counts on this machine, not a capacity: the mock answers
faster than the real provider here so that the bend is reached with few virtual users, and the
load generator shares the CPU with the replicas. `REPLICAS`, `LEVELS`, `HOLD` and `BEND` change
the run; see the top of the script. The test guests are deleted from the local database at the
end.

To refresh the local wait times from the demo database (tunnel open), with
`backend/script.demo.local.sh`:

```bash
./script.demo.local.sh query "select coalesce(json_agg(w), '[]'::json)::text from wait_times w" \
  | tail -n +2 > ../artifacts/demo-seed/wait_times.json
./script.demo.local.sh --local query "delete from wait_times"
./script.demo.local.sh --local query "insert into wait_times select * from \
  json_populate_recordset(null::wait_times, '$(sed "s/'/''/g" ../artifacts/demo-seed/wait_times.json)'::json)"
```
