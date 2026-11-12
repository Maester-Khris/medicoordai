# Security review: Sprint 23 diff (graph v3 semantic path, LLM guards, eval)

Scope: runtime backend code added on `feat/eval-hardening` since `preview` (23 files, about 2,250 added lines: `graph/semantic/*`, `graph/snomed_neo4j/semantic_provider.py`, `llm/{breaker,retry,spend}.py`, `services/llm_agent.py`, `routers/chat.py`, `main.py`, `middleware/*`, `config.py`), read from the review worktree `chore/security-review` @ d539d08. Method: read-only code reading and search, confidence threshold 8 of 10. Tests and offline scripts excluded.

# Result: no findings at confidence 8 or above

No vulnerability in the sprint-added runtime code reaches the reporting threshold. Paths traced and found sound:

| Area | Where | Why it holds |
|---|---|---|
| Model/index deserialization | `graph/semantic/index.py:220` | `np.load(..., allow_pickle=False)`; manifest and rows are JSON |
| Command execution | `graph/semantic/build.py:334,372` | The only subprocess takes a fixed argument list (`nice`, `sys.executable`, module name, `run`); no request, user or model text reaches it |
| Cypher injection | `graph/snomed_neo4j/queries.py` | Concept and anchor ids are bound parameters; the only interpolated value, `max_depth`, is a validated int from the static anchor table |
| SQL injection | `services/guest_store.py`, `services/facilities.py` | Every value is a bound parameter; interpolated names are module constants |
| Guest isolation | `routers/chat.py:114-145`, `guest_store.add_message` | Ownership is enforced in one statement before the agent or the spend counter is touched, so a guest cannot read, write or draw down another guest's session |
| Routing abuse | `routers/routes.py` | The request carries facility ids only; coordinates come from the server's own list, so the endpoint cannot route between arbitrary points |
| Spend cap keys | `llm/spend.py:66,80` | Keyed by a UUID session id that must pass the ownership check first |
| Metrics endpoint | `observability.py:70-76` | Fails closed when no token is configured |
| Cross-origin | `main.py` | Explicit origin list, no wildcard (S5 probe) |

# Considered and not reported (confidence below 8, or excluded by the review rules)

* **ONNX model integrity** (`graph/semantic/build.py:87-102`, `embedder.py:81`): `model_sha256` is read from `export.json` next to the model and is never compared with the `.onnx` bytes. Exploiting it needs write access to the index/model volume, which is already a deployment compromise. Recorded as a Medium hardening item in the Sprint 23 changelog.
* **Prompt fence in the graph block** (`llm/prompts.py:101-122`): graph fields are interpolated without escaping, so a poisoned entry could forge the closing tags. A guest cannot write that data (curated file audited clean; the SNOMED pipeline output is not reachable from this machine), and prompt-content issues are excluded by the review rules. Recorded as Medium with a plan.
* **`X-Real-IP` trusted first** (`services/rate_limit.py:29`): lets a client that reaches the app without the proxy pick its rate-limit bucket. Rate limiting is excluded.
* **Metrics token compared with `!=`**: a timing channel on a high-entropy bearer; theoretical, excluded.
* **Blocking Supabase call for any `Bearer` header in demo mode** (`middleware/auth.py`): a real availability issue found and fixed in this review (commit ce1c71b); denial of service is excluded from this report's scope.
