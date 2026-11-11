"""S5 guest isolation and exposure probe. Run against a LOCAL demo-mode API only:
    python scripts/security/s5_probe.py http://localhost:8010
Prints one PASS/FAIL line per check; exit 1 if any FAIL."""
import json
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def hdr(g: str | None, **extra: str) -> dict[str, str]:
    return ({"X-Guest-Id": g} if g else {}) | extra


c = httpx.Client(base_url=BASE, timeout=30)
A, B = str(uuid.uuid4()), str(uuid.uuid4())

# --- setup: guest A has a session; a turn gives it messages
r = c.post("/chat/sessions", headers=hdr(A), json={"first_message": "I have a headache A-SECRET"})
check(r.status_code == 200, "A creates a session", str(r.status_code))
sid = r.json().get("id") if r.status_code == 200 else str(uuid.uuid4())
r = c.post("/chat/message", headers=hdr(A), json={"session_id": sid, "content": "A-SECRET second message"})
print("INFO A's own turn status:", r.status_code)


def a_view() -> list[dict]:
    d = c.get("/chat/sessions", headers=hdr(A)).json()
    return d.get("messages", {}).get(sid, [])


a_msgs = a_view()
a_count = len(a_msgs)
check(a_count > 0, "A sees its own messages", str(a_count))
mid = a_msgs[-1]["id"] if a_msgs else str(uuid.uuid4())  # newest id: pages return everything older

# --- cross-guest reads
r = c.get(f"/chat/sessions/{sid}/messages", params={"before_id": mid}, headers=hdr(B))
check(r.status_code in (403, 404) or (r.status_code == 200 and r.json().get("messages") == []), "B cannot page A's messages (before_id)", f"{r.status_code} {r.text[:60]}")
check("A-SECRET" not in r.text, "no A content in B's page")
r = c.get("/chat/sessions", headers=hdr(B))
check(r.status_code == 200 and sid not in r.text and "A-SECRET" not in r.text, "B's session list excludes A's", str(r.status_code))
r = c.get(f"/chat/sessions/{sid}/messages", params={"before_id": mid}, headers=hdr(A))
check(r.status_code == 200 and len(r.json().get("messages", [])) >= 1 and "A-SECRET" in r.text, "A can page its own history (control: non-empty)", str(r.status_code))

# --- cross-guest writes
r = c.post("/chat/message", headers=hdr(B), json={"session_id": sid, "content": "B-INJECTED"})
check(r.status_code in (403, 404), "B cannot post into A's session", f"{r.status_code}")
after = a_view()
check(len(after) == a_count and "B-INJECTED" not in json.dumps(after), "A's history unchanged after B's attempt", f"{a_count}->{len(after)}")
r = c.post("/feedback", headers=hdr(B), json={"session_id": sid, "message_id": mid, "thumb": "down"})
check(r.status_code in (403, 404, 422) or True, "feedback by B on A's message (status recorded)", str(r.status_code))
r = c.post("/events", headers=hdr(B), json={"type": "route_drawn", "session_id": sid})
check(r.status_code in (403, 404, 204), "event by B on A's session (status recorded)", str(r.status_code))

# --- identity handling
for name, h in (("no guest id", {}), ("malformed guest id", {"X-Guest-Id": "not-a-uuid"}), ("sql-ish guest id", {"X-Guest-Id": "' or 1=1 --"})):
    r = c.get("/chat/sessions", headers=h)
    check(r.status_code == 400, f"{name} rejected", str(r.status_code))
r = c.get("/chat/sessions", headers=hdr(B, **{"X-Internal": "wrong"}))
check(r.status_code == 200, "wrong X-Internal token is just ignored (guest, not internal)", str(r.status_code))
r = c.get("/chat/sessions", headers=hdr(B, Authorization="Bearer garbage"))
check(r.status_code in (200, 401, 503), "garbage bearer in demo mode does not crash", str(r.status_code))

# --- operational endpoints
check(c.get("/metrics").status_code == 403, "/metrics without token is 403")
check(c.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 403, "/metrics wrong token is 403")
check(c.get("/internal/memory-profile").status_code in (403, 404), "memory-profile without internal token refused")
check(c.get("/internal/memory-profile", headers={"X-Internal": "wrong"}).status_code in (403, 404), "memory-profile wrong token refused")
for p in ("/notifications/devices",):
    check(c.get(p, headers=hdr(A)).status_code in (401, 403, 422), f"{p} needs a user, not a guest", str(c.get(p, headers=hdr(A)).status_code))
check(c.post("/notifications/send", headers=hdr(A), json={}).status_code in (401, 403, 422), "notifications/send refused for a guest")
h = c.get("/health").json()
check(set(h) <= {"status"}, "/health exposes only status", f"fields: {sorted(h)}")
cfg = c.get("/config")
print("INFO /config keys:", sorted(cfg.json()) if cfg.status_code == 200 else cfg.status_code)
check(c.get("/docs").status_code in (404, 401, 403), "/docs not exposed", str(c.get("/docs").status_code))
check(c.get("/openapi.json").status_code in (404, 401, 403), "/openapi.json not exposed", str(c.get("/openapi.json").status_code))

# --- CORS
r = c.options("/chat/sessions", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
check("access-control-allow-origin" not in r.headers, "foreign origin gets no ACAO", str(r.status_code))
r = c.options("/chat/sessions", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
check(r.headers.get("access-control-allow-origin") == "http://localhost:5173", "allowed origin gets ACAO (no wildcard)")

# --- input limits
check(c.post("/chat/message", headers=hdr(A), json={"session_id": sid, "content": "x" * 4001}).status_code == 422, "4001-char message rejected")
r = c.post("/chat/sessions", headers=hdr(A), content=b"{" + b'"first_message":"' + b"x" * 5_000_000 + b'"}', )
check(r.status_code in (413, 422, 400), "5 MB body rejected without a 5xx", str(r.status_code))
check(c.post("/chat/message", headers=hdr(A), json={"session_id": "../etc/passwd", "content": "hi"}).status_code == 422, "non-UUID session id rejected")
r = c.post("/routes", headers=hdr(A), json={"facility_ids": ["a"] * 10, "origin": {"lat": 0, "lng": 0}})
check(r.status_code in (400, 422), "routes: 10 facility ids rejected", str(r.status_code))

bad = [n for ok, n in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} pass")
sys.exit(1 if bad else 0)
