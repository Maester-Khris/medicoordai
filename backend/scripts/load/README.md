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

# Test B, chat. Spends LLM quota on every turn.
docker run --rm -i --network host --user "$(id -u):$(id -g)" \
  -e BASE_URL=https://<api-under-test> -e INTERNAL_TOKEN="$DEMO_INTERNAL_TOKEN" -e STEPS=1,2,5,10,20,40 \
  -v "$PWD/backend/scripts/load:/scripts:ro" -v "$PWD/artifacts/perf:/out" \
  grafana/k6 run /scripts/test_b.js --summary-export /out/test-b.json
```

Before a run against a deployed API:

- Never point these at the public demo service. The target is the staging service.
- Raise `RATE_LIMIT_CHAT_IP` and `RATE_LIMIT_ROUTES_IP` on the target: every request comes from
  one IP, and with the defaults the test measures the limiter after 30 chat turns.
- Set `DEMO_INTERNAL_TOKEN` on the target and pass the same value as `INTERNAL_TOKEN`, so the
  guests the test creates are marked internal and can be deleted afterwards.
- Set `ROUTING_SHADOW_SAMPLE_RATE=0` on the target for Test B: the shadow comparison makes an
  extra Geoapify call on a share of chat turns.

`POST /routes` is capped at 2 requests per second in every Test A scenario because each request
makes three calls on the metered Geoapify key. Transit is not exercised under load.
