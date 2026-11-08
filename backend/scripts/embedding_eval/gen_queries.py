"""Generate lay-language test messages with an LLM, hiding the complaint name from the message writer,
then label them blind. Costs money (about $0.04 for pass 1, $0.015 for pass 2 on gpt-4o-mini): run it
deliberately, under Doppler with OPENAI_API_KEY set. Writes to results/ (git-ignored); copy a result
into data/ to keep it.

  python -m scripts.embedding_eval.gen_queries first           # every anchor
  python -m scripts.embedding_eval.gen_queries weak            # re-do anchors the labeler could not confirm in pass 1

Pipeline per anchor: (1) the complaint name becomes a plain description of what the person experiences;
(2) four messages are written from that description alone, in four voices; (3) a blind labeler returns
its top 3 categories per message. A message is "valid" when its gold anchor is in the labeler's top 3.
Model name comes from EVAL_GEN_MODEL (default gpt-4o-mini).
"""
import argparse
import collections
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS

HERE = Path(__file__).resolve().parent
DATA, RESULTS = HERE / "data", HERE / "results"
MODEL = os.environ.get("EVAL_GEN_MODEL", "gpt-4o-mini")
PRICE_IN, PRICE_OUT = 0.15 / 1e6, 0.60 / 1e6  # gpt-4o-mini list prices per token (third-party tracker; verify)
HARD_STOP_USD = 0.10
NAMES = [m.ctas_alias for m in ANCHOR_MAPPINGS]
# three complaint names carry PDF text-wrap artifacts from the CTAS source (see anchor_mapping.py)
CLEAN_NAMES = {3: "Chest pain (non cardiac features)", 4: "Palpitations / Irregular heart beat", 6: "General weakness"}
SKIP = {66, 110, 149, 150, 153}  # social problem, welfare concern, device, lab values, newborn: not symptom descriptions
VOICES = ["an adult describing their own problem in a few natural sentences",
          "a worried parent, partner or bystander describing someone else",
          "an older, hesitant person who avoids technical words",
          "someone typing very briefly and casually, lowercase, maybe a typo"]
WEAK_THRESHOLD = 0.5
client = OpenAI()
spent = {"in": 0, "out": 0}


def name_of(idx: int) -> str:
    return CLEAN_NAMES.get(idx, NAMES[idx])


def cost_usd() -> float:
    return spent["in"] * PRICE_IN + spent["out"] * PRICE_OUT


def chat(system: str, user: str, json_mode: bool = False, temperature: float = 0.7, max_tokens: int = 700) -> str:
    if cost_usd() > HARD_STOP_USD:
        raise SystemExit(f"hard cost stop at ${cost_usd():.3f}")
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    reply = client.chat.completions.create(
        model=MODEL, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
    spent["in"] += reply.usage.prompt_tokens
    spent["out"] += reply.usage.completion_tokens
    return reply.choices[0].message.content


def json_chat(system: str, user: str, **kwargs) -> dict:
    for attempt in range(3):  # the model occasionally returns malformed JSON
        try:
            return json.loads(chat(system, user, json_mode=True, **kwargs))
        except json.JSONDecodeError:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def describe(idx: int, detailed: bool) -> str:
    cues = ("Be specific about the facts that DEFINE this category and separate it from the most similar categories "
            "(the cause or mechanism, the body part, the age group, the timing, the severity), in everyday words. ") if detailed else ""
    return chat("You write neutral descriptions for a medical-triage evaluation dataset.",
                f"Complaint category: {name_of(idx)}\nIn {3 if detailed else '2 or 3'} plain sentences, describe what a person with this problem "
                f"experiences or what an observer would see. {cues}Do NOT name the complaint, give its synonyms, or use a diagnosis label.",
                temperature=0.3, max_tokens=220 if detailed else 160).strip()


def write_messages(description: str, detailed: bool) -> list[str]:
    cues = ("Each message must include the defining facts of the situation (cause or how it happened, body part, who it affects, when) "
            "in everyday words. ") if detailed else ""
    user = ("Situation (do not repeat it verbatim):\n" + description +
            "\n\nWrite 4 different messages a layperson might type to a health chatbot about this situation, one per voice:\n" +
            "\n".join(f"{n + 1}. {v}" for n, v in enumerate(VOICES)) +
            f"\n{cues}Use everyday words only: no medical terms, no diagnoses. 8 to {40 if detailed else 35} words each. "
            'Return JSON: {"messages": ["...","...","...","..."]}')
    return json_chat("You write realistic patient messages for an evaluation dataset.", user,
                     temperature=0.9, max_tokens=600)["messages"][:4]


def label_batch(batch: list[tuple[int, str]], catalog: str) -> list[dict]:
    listing = "\n".join(f"[{n}] {m}" for n, (_, m) in enumerate(batch))
    got = {x["n"]: x["top3"] for x in json_chat(
        "You are a triage nurse assigning patient messages to presenting-complaint categories.",
        f"Categories:\n{catalog}\n\nFor each message, give the 3 most likely category numbers (best first).\n\nMessages:\n{listing}\n\n"
        'Return JSON: {"labels": [{"n": 0, "top3": [12, 4, 7]}, ...]} with one entry per message.',
        temperature=0, max_tokens=1300)["labels"]}
    labeled = []
    for n, (idx, message) in enumerate(batch):
        top3 = got.get(n, [])
        labeled.append({"idx": idx, "expected_complaint": NAMES[idx], "message": message, "labeler_top3": top3,
                        "agree_top1": bool(top3) and top3[0] == idx, "agree_top3": idx in top3})
    return labeled


def weak_anchors(labeled: list[dict], threshold: float = WEAK_THRESHOLD) -> list[int]:
    """Anchors whose messages the labeler confirmed (gold in its top 3) less often than the threshold."""
    agreement: dict[int, list[bool]] = collections.defaultdict(list)
    for item in labeled:
        agreement[item["idx"]].append(item["agree_top3"])
    return sorted(i for i, flags in agreement.items() if sum(flags) / len(flags) < threshold)


def run(indices: list[int], detailed: bool, seed: int) -> list[dict]:
    with ThreadPoolExecutor(8) as pool:
        descriptions = dict(zip(indices, pool.map(lambda i: describe(i, detailed), indices)))
        messages = dict(zip(indices, pool.map(lambda i: write_messages(descriptions[i], detailed), indices)))
    items = [(i, m) for i, ms in messages.items() for m in ms]
    random.Random(seed).shuffle(items)
    catalog = "\n".join(f"{i}: {name_of(i)}" for i in range(len(NAMES)) if i not in SKIP)
    with ThreadPoolExecutor(6) as pool:
        batches = pool.map(lambda start: label_batch(items[start:start + 20], catalog), range(0, len(items), 20))
        return [item for batch in batches for item in batch]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pass_name", choices=["first", "weak"])
    parser.add_argument("--from", dest="first_pass", type=Path, default=DATA / "generated_pass1_labeled.json")
    args = parser.parse_args()
    if args.pass_name == "first":
        indices, detailed, seed = [i for i in range(len(NAMES)) if i not in SKIP], False, 7
    else:
        indices, detailed, seed = weak_anchors(json.loads(args.first_pass.read_text())), True, 11
    labeled = run(indices, detailed, seed)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"generated_{args.pass_name}_labeled.json"
    out.write_text(json.dumps(labeled, indent=1))
    n = len(labeled)
    print(f"{n} messages over {len(indices)} anchors -> {out}; labeler top1 {sum(x['agree_top1'] for x in labeled) / n:.3f} "
          f"top3 {sum(x['agree_top3'] for x in labeled) / n:.3f}; est ${cost_usd():.4f}")


if __name__ == "__main__":
    main()
