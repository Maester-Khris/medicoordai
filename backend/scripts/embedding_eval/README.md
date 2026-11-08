# Embedding model comparison for lay-symptom retrieval (Sprint 23, steps 3-4)

Offline experiment: which small embedding model best maps a lay-language symptom message to one of the
154 CTAS/SNOMED anchors, and what does it cost on CPU. Nothing here touches the live providers.

## Decision status (2026-11-08)
- **Working choice: BioLORD-2023.** Highest quality on every query set.
- **Not final.** An end-to-end test will run **both BioLORD-2023 and bge-small-en-v1.5** later, and the one kept for
  the public deployment is chosen on **latency, CPU cost and quality** together.
- Open: ONNX int8 timing on the Railway box type (not measured). English only for now. S-PubMedBert-MS-MARCO is
  cc-by-nc: fine while the project is non-commercial, a blocker if that changes. BioLORD needs UMLS/SNOMED licensing.

## Results
Hit rate of the gold anchor, best target-set setting per model. Substring matching (today's providers) is the baseline.
"+ aliases" adds the CTAS complaint names and v1 aliases to the targets (a stand-in for the lay descriptions still to be written).

| Model | Params | Single message, torch fp32, 8-core laptop | Author-written set (150): hit@1 / hit@5 | Independent valid set (469): hit@5, SNOMED only | + aliases: hit@1 / hit@5 [95% CI] |
|---|---|---|---|---|---|
| substring (today) | – | – | 16 / 16 hits | about 10% | – |
| **BioLORD-2023** | 110M | 57.8 ms | 113 / 146 (97%) | 83% | 52% / 87% [84-90] |
| bge-small-en-v1.5 | 33M | 14.6 ms | 91 / 134 (89%) | 65% | 47% / 78% [74-81] |
| SapBERT | 110M | 53.2 ms | 70 / 102 | 52% | 36% / 62% |
| S-PubMedBert-MS-MARCO | 110M | 47.3 ms | 61 / 103 | 50% | 32% / 61% |

- The **author-written** set is optimistic: the messages were written from the anchor list. The **independent** set was written by
  gpt-4o-mini from a description with the complaint name hidden, then kept only if a blind labeler put the gold anchor in its top 3
  (469 valid messages over 140 anchors, from two generation passes).
- Adding SNOMED descendants (depth 1-2) lowered hit rates for every model (anchors with thousands of targets win by volume):
  limit depth in the graph rebuild. Averaging the top-3 targets per anchor helps slightly.
- Laptop latencies are relative only. The Railway 1 vCPU will be slower; ONNX int8 should be faster. Measure before deciding.

## Layout
- `build_targets.py` - 19,054 target strings per anchor from the SNOMED CA edition (needs `/databank` RF2 files, override with `SNOMED_CA_TERMINOLOGY_DIR`).
- `embed_eval.py` - embed targets and queries with one model and score; `lexical` is the substring baseline.
- `gen_queries.py` - LLM-written test messages (costs money, needs `OPENAI_API_KEY`; see its docstring).
- `scoring.py` - pure ranking and statistics helpers (unit-tested).
- `data/` - the query sets with gold anchors and labeler output. `cache/` and `results/` are git-ignored.

## Run (from `backend/`, under Doppler, pydev environment)
    python -m scripts.embedding_eval.build_targets
    python -m scripts.embedding_eval.embed_eval biolord --tag author --latency
    python -m scripts.embedding_eval.embed_eval biolord --tag generated --valid-only \
        --queries data/generated_pass1_labeled.json data/generated_pass2_labeled.json
Models download from Hugging Face on first use (about 1.6 GB for all four; set `HF_HOME` to relocate). torch, transformers and
numpy come in through `deepeval`; nothing was added to `requirements.txt`.

## Caveats
Synthetic queries (not real guest messages); some messages fit more than one anchor, which understates hit@1; the validity filter
favours messages an LLM can label; 29 trauma-mechanism and rare anchors needed a second generation pass and 9 anchors still have no valid message.
