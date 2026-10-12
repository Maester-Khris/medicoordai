"""Local proof that the API scales by adding replicas (spec section 8.3).

Brings the Compose stack up at each replica count and runs four checks:
  1. throughput at the bend of the latency curve grows with replicas;
  2. a conversation whose turns land on different replicas keeps its history;
  3. the load counters summed in Redis equal the recommendations made, one field per replica;
  4. stopping one replica mid-run leaves the others serving.

Run from the repository root, with the pydev environment active and the local demo database
container (medicoord-demo-pg) running with facilities and wait times loaded:

    python backend/scripts/load/compose/run_horizontal.py

Settings (environment):
    REPLICAS   replica counts to compare (default 1,2,4)
    LEVELS     concurrent conversations tried in turn, per replica count
               (default 40,80,120,160,240,320,480,640)
    HOLD       how long each level is held (default 40s)
    BEND       a level is past the bend when its turn p95 exceeds this multiple of the first
               level's p95 (default 2.0)

The numbers are a ratio between replica counts on this machine, not a capacity: the mock answers
faster than the real provider (MOCK_LLM_MEAN_S in docker-compose.yml) and the load generator
shares the CPU with the replicas. The report goes to artifacts/perf/.
"""
import concurrent.futures
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
COMPOSE = ["docker", "compose", "-f", str(HERE / "docker-compose.yml")]
OUT = REPO / "artifacts" / "perf" / "compose"
API = "http://127.0.0.1:8088"
MOCK = "http://127.0.0.1:8089"
TOKEN = "compose-internal-token"  # same value as DEMO_INTERNAL_TOKEN in docker-compose.yml
NETWORK = "medicoord-load_default"
DB_CONTAINER = "medicoord-demo-pg"

REPLICAS = [int(n) for n in os.environ.get("REPLICAS", "1,2,4").split(",")]
LEVELS = [int(n) for n in os.environ.get("LEVELS", "40,80,120,160,240,320,480,640").split(",")]
HOLD = os.environ.get("HOLD", "40s")
BEND = float(os.environ.get("BEND", "2.0"))
HOLD_SECONDS = int(HOLD.rstrip("s")) + 10  # plus the ramp of each step


def sh(*cmd: str, check: bool = True) -> str:
    done = subprocess.run(cmd, capture_output=True, text=True)
    if check and done.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{done.stderr.strip()}")
    return done.stdout.strip()


def _answered_by(headers) -> str:
    # nginx lists every replica it tried ("a, b") when it skipped one that was not reachable.
    return headers.get("X-Upstream", "").split(",")[-1].strip()


def call(method: str, url: str, body: dict | None = None, guest: str | None = None) -> tuple[int, str, dict]:
    """(status, replica that answered, parsed body). A refused connection is status 0."""
    headers = {"Content-Type": "application/json", "X-Internal": TOKEN}
    if guest:
        headers["X-Guest-Id"] = guest
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, _answered_by(response.headers), json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, _answered_by(error.headers), {}
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, "", {}


def conversation(turns: int) -> dict:
    """One guest, one session, `turns` messages. Returns what the checks need."""
    guest = str(uuid.uuid4())
    status, _, session = call("POST", f"{API}/chat/sessions", {"first_message": "chest pain"}, guest)
    result = {"ok": status == 200, "replicas": set(), "recommendations": 0, "turns_ok": 0}
    if status != 200:
        return result
    for _ in range(turns):
        body = {"session_id": session["id"], "content": "chest pain, getting worse", "lat": 43.70, "lng": -79.40}
        status, replica, reply = call("POST", f"{API}/chat/message", body, guest)
        if status != 200:
            result["ok"] = False
            break
        result["turns_ok"] += 1
        result["replicas"].add(replica)
        if (reply.get("triage") or {}).get("recommended_facility"):
            result["recommendations"] += 1
    return result


def redis(*args: str) -> list[str]:
    return sh(*COMPOSE, "exec", "-T", "redis", "redis-cli", "--raw", *args).splitlines()


def replicas_answering() -> set[str]:
    return {call("GET", f"{API}/health")[1] for _ in range(40)} - {""}


def scale(count: int) -> None:
    sh(*COMPOSE, "up", "-d", "--scale", f"api={count}")
    sh("docker", "network", "connect", NETWORK, DB_CONTAINER, check=False)  # already attached is fine
    sh(*COMPOSE, "restart", "nginx")  # so it learns the replica addresses
    deadline = time.time() + 90
    while time.time() < deadline:
        # The mock is checked too: a replica is healthy before its provider is listening.
        if call("GET", f"{MOCK}/health")[0] == 200 and len(replicas_answering()) == count:
            return
        time.sleep(2)
    sys.exit(f"{count} replicas did not come up behind nginx")


def k6(level: int, name: str, background: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        "docker", "run", "--rm", "-i", "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}",
        "-e", f"BASE_URL={API}", "-e", f"INTERNAL_TOKEN={TOKEN}", "-e", f"STEPS={level}", "-e", f"STEP_HOLD={HOLD}",
        "-v", f"{REPO / 'backend/scripts/load'}:/scripts:ro", "-v", f"{OUT}:/out",
        "grafana/k6", "run", "/scripts/test_b.js", "--quiet", "--summary-export", f"/out/{name}.json",
    ]
    if background:
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return summary(name)


def summary(name: str) -> dict:
    metrics = json.loads((OUT / f"{name}.json").read_text())["metrics"]
    ok = metrics.get("chat_turns_ok", {}).get("count", 0)
    return {
        "turns_ok": ok,
        "turns_per_second": round(ok / HOLD_SECONDS, 1),
        "p95_ms": round(metrics.get("chat_turn_duration", {}).get("p(95)", 0)),
        "failed": round(metrics.get("chat_turn_failed", {}).get("value", 0), 4),
        "busy": round(metrics.get("chat_turn_busy", {}).get("value", 0), 4),
    }


def check_history(count: int) -> dict:
    call("POST", f"{MOCK}/stats/reset")
    turns = 6
    result = conversation(turns)
    seen = call("GET", f"{MOCK}/stats")[2].get("max_user_turns_seen", 0)
    # The LLM must be sent every earlier user message, whichever replica handles the turn.
    passed = result["ok"] and seen == turns and len(result["replicas"]) == min(count, turns)
    return {"passed": passed, "replicas_used": len(result["replicas"]), "user_turns_seen_by_llm": seen, "turns": turns}


def check_counters(count: int) -> dict:
    redis("flushall")
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: conversation(3), range(10 * count)))
    recommendations = sum(r["recommendations"] for r in results)
    time.sleep(2)  # the write to Redis is handed to a thread after the reply
    total, instances = 0, set()
    for key in redis("keys", "load:*"):
        fields = redis("hgetall", key)
        for field, value in zip(fields[::2], fields[1::2]):
            total += int(value)
            instances.add(field.split("|")[1])
    passed = recommendations > 0 and total == recommendations and len(instances) == count
    return {"passed": passed, "recommendations": recommendations, "redis_total": total, "instances": len(instances)}


def find_bend(count: int) -> dict:
    """Raises the level until turn p95 leaves the flat part, and keeps the best throughput before it."""
    rows, best, base_p95 = [], None, None
    for level in LEVELS:
        row = {"level": level, **k6(level, f"r{count}-l{level}")}
        base_p95 = base_p95 or row["p95_ms"]
        row["past_bend"] = row["p95_ms"] > BEND * base_p95 or row["failed"] > 0.05 or row["busy"] > 0.05
        rows.append(row)
        print(f"    {count} replica(s), {level:>4} conversations: {row['turns_per_second']:>6} turns/s, "
              f"p95 {row['p95_ms']} ms{'  <- past the bend' if row['past_bend'] else ''}", flush=True)
        if row["past_bend"]:
            break
        if best is None or row["turns_per_second"] > best["turns_per_second"]:
            best = row
    return {"rows": rows, "best": best, "bend_reached": rows[-1]["past_bend"]}


def check_failover(count: int) -> dict:
    """Stops one replica 20 s into a run. The turns in flight on it are lost; the rest must go on."""
    run = k6(40, f"r{count}-failover", background=True)
    time.sleep(20)
    victim = sh(*COMPOSE, "ps", "-q", "api").splitlines()[0]
    sh("docker", "stop", "-t", "0", victim)
    run.wait()
    during = summary(f"r{count}-failover")
    after = [conversation(2) for _ in range(5)]
    passed = during["failed"] < 0.25 and during["turns_ok"] > 0 and all(r["ok"] for r in after)
    return {"passed": passed, "failed_share_during": during["failed"], "turns_ok_during": during["turns_ok"],
            "conversations_ok_after": sum(r["ok"] for r in after), "replicas_left": len(replicas_answering())}


def main() -> None:
    report: dict = {"replicas": {}, "levels": LEVELS, "hold": HOLD, "bend_factor": BEND}
    try:
        for count in REPLICAS:
            print(f"== {count} replica(s)", flush=True)
            scale(count)
            entry = {"history": check_history(count), "counters": check_counters(count)}
            print(f"    history across replicas: {entry['history']}", flush=True)
            print(f"    load counters: {entry['counters']}", flush=True)
            entry["throughput"] = find_bend(count)
            report["replicas"][count] = entry
        last = REPLICAS[-1]
        if last > 1:
            report["failover"] = check_failover(last)
            print(f"== failover at {last} replicas: {report['failover']}", flush=True)
    finally:
        sh("docker", "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "medicoord_demo", "-qc",
           "delete from guests where is_internal", check=False)
        sh("docker", "network", "disconnect", NETWORK, DB_CONTAINER, check=False)
        sh(*COMPOSE, "down", check=False)

    base = report["replicas"][REPLICAS[0]]["throughput"]["best"]
    lines = ["| Replicas | Best level | Turns/s at the bend | p95 there (ms) | Ratio | Bend reached |", "|---|---|---|---|---|---|"]
    for count in REPLICAS:
        throughput = report["replicas"][count]["throughput"]
        best = throughput["best"]
        if best is None:
            lines.append(f"| {count} | none | n/a | n/a | n/a | first level already past the bend |")
            continue
        ratio = round(best["turns_per_second"] / base["turns_per_second"], 2) if base else "n/a"
        lines.append(f"| {count} | {best['level']} | {best['turns_per_second']} | {best['p95_ms']} | {ratio} | "
                     f"{'yes' if throughput['bend_reached'] else 'no, the levels ran out'} |")
    table = "\n".join(lines)
    stamp = datetime.date.today().isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{stamp}-horizontal.json").write_text(json.dumps(report, indent=1, default=list))
    print("\n" + table)
    print(f"\nraw results: {OUT / f'{stamp}-horizontal.json'}")


if __name__ == "__main__":
    main()
