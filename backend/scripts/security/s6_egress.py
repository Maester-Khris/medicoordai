"""S6: what leaves for the model and routing providers. Run against a LOCAL demo-mode API whose
provider base URLs point at a capture proxy that appends each request to a JSONL file.
    python scripts/security/s6_egress.py http://localhost:8010 /path/to/capture.jsonl"""
import json
import sys
import uuid

import httpx

BASE, CAP = sys.argv[1], sys.argv[2]
G = str(uuid.uuid4())
IP = "203.0.113.77"                      # documentation range: easy to search for
LAT, LNG = 43.6532123, -79.3832456
FREE_TEXT = "My name is Margaret Tremblay, phone 416-555-0199, email m.tremblay@example.com, I live at 55 Elm Street. I have crushing chest pain and my left arm is numb."
results: list[bool] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


c = httpx.Client(base_url=BASE, timeout=60)
H = {"X-Guest-Id": G, "X-Forwarded-For": IP, "User-Agent": "s6-probe/1.0"}
open(CAP, "w").close()
sid = c.post("/chat/sessions", headers=H, json={"first_message": FREE_TEXT}).json()["id"]
turns = 0
for text in (FREE_TEXT, "It started an hour ago and I feel sweaty and short of breath.", "Please tell me where to go."):
    r = c.post("/chat/message", headers=H, json={"session_id": sid, "content": text, "lat": LAT, "lng": LNG})
    turns += r.status_code == 200
facs = c.get("/facilities").json()
ids = [f["id"] for f in facs][:2] if isinstance(facs, list) else []
if ids:
    r = c.post("/routes", headers=H, json={"facility_ids": ids, "origin": {"lat": LAT, "lng": LNG}, "mode": "car"})
    check(r.status_code == 200, "/routes call succeeded (routing path exercised)", str(r.status_code))

cap = [json.loads(line) for line in open(CAP)]
model = [x for x in cap if "chat/completions" in x["path"]]
routing = [x for x in cap if x not in model]
print(f"INFO turns ok: {turns}; captured model requests: {len(model)}; other provider requests: {len(routing)} {sorted({x['path'] for x in routing})}")
check(len(model) >= 3, "model requests were captured", str(len(model)))


def blob(x: dict) -> str:
    return (json.dumps(x["headers"]) + x["path"] + x["query"] + x["body"]).lower()


secrets = {"guest id": G, "session id": sid, "client IP": IP, "latitude": "43.6532", "longitude": "79.3832", "user agent": "s6-probe"}
for name, val in secrets.items():
    leaked = sum(val.lower() in blob(x) for x in model)
    check(leaked == 0, f"no {name} in any model request (headers + body)", f"{leaked}/{len(model)} contain it")
# data that is sent on purpose or by absence of a detector: report, do not fail
for name, val in {"typed name": "Margaret Tremblay", "typed phone": "416-555-0199", "typed email": "m.tremblay@example.com", "typed street": "55 Elm Street"}.items():
    n = sum(val.lower() in blob(x) for x in model)
    print(f"FINDING {name} reaches the model provider unredacted in {n}/{len(model)} requests")
fac = sum("test general hospital" in blob(x) or "test walk-in" in blob(x) for x in model)
print(f"INFO facility name/address (public data) in {fac} model requests")
for name, val in {"guest id": G, "client IP": IP}.items():
    check(sum(val in blob(x) for x in routing) == 0, f"no {name} in routing-provider requests")
print("INFO coordinates in routing requests (by design):", sum("43.6532" in blob(x) for x in routing), "of", len(routing))
bad = results.count(False)
print(f"\n{len(results) - bad}/{len(results)} pass")
sys.exit(1 if bad else 0)
