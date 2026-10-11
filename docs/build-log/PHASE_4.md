# Phase 4 — Retrieval

**Goal:** for any question, find the few chunks the LLM should answer from, and know when nothing relevant exists.

```
question ─┬─► vector search  (top 20, cosine, HNSW) ─┐
          │                                          ├─► RRF ─► Cohere rerank ─► top 5 ─► relevance gate
          └─► keyword search (top 20, OR, GIN)     ─┘
```

## What was built and why

| File | What it does | Why |
|---|---|---|
| `app/retrieval/search.py` | `vector_search`, `keyword_search`, `reciprocal_rank_fusion`; optional product and doc-type filters | Each search catches what the other misses. Keyword terms are OR-ed, so one unmatched word ("jog") doesn't wipe out all results |
| `app/retrieval/reranker.py` | Cohere `rerank-v3.5` (via LangChain) with retry on 429/5xx only; `OverlapReranker` for offline tests | The reranker reads question + chunk together, so it puts the true best chunk first. A bad key fails fast instead of retrying |
| `app/retrieval/retriever.py` | `Retriever.retrieve(question, mode)` for 4 modes: `vector`, `keyword`, `hybrid`, `hybrid_rerank`; returns chunks, scores, ranks in each list, timings, gate result | One function the agent will call in Phase 5; the modes let the eval measure each stage |
| `scripts/ask.py` (`make ask q="..."`) | Prints every stage for one question | See why a chunk ranked where it did |
| `scripts/eval_retrieval.py` (`make eval-retrieval`) | Scores all modes on the golden questions, calibrates the gate, lists misses, writes `evals/reports/retrieval.md`; exits non-zero below hit@5 0.85 | Decisions by numbers; ready for CI |
| `evals/.cache/` (git-ignored) | Caches query embeddings and rerank results on disk | The first run cost 1 embed + 94 rerank calls; every re-run costs 0 |

## Results (87 answerable golden questions)

| Mode | hit@1 | hit@3 | hit@5 | MRR@5 |
|---|---|---|---|---|
| vector | 0.80 | 0.95 | 0.98 | 0.88 |
| keyword | 0.78 | 0.97 | 0.98 | 0.87 |
| hybrid | 0.82 | 0.99 | 0.99 | 0.90 |
| **hybrid + rerank** | **0.89** | **0.99** | **0.99** | **0.93** |

- **Target met:** hit@5 0.99 vs 0.85.
- **What each stage adds:** hybrid fixes recall (the right document reaches the top 3 for 99%); rerank fixes order (#1 correct goes from 82% to 89%). Order matters because the LLM leans hardest on the first chunks.
- **The one miss** (g092, repair prices) is a question the docs can't answer; the expected VoltCare page is only a side note.
- **Keyword alone is surprisingly strong** here, because golden questions often reuse document words. Real customers paraphrase more, so vector search matters more in production.

## Relevance gate: why 0.15, not the "best" 0.5

Top rerank score: answerable median 0.815; off-topic questions 0.018 to 0.047.

The script's accuracy-maximising threshold was 0.5, but the lowest-scoring *answerable* questions were "no" questions: "Do you ship to the UK?" (0.206, answer: Canada only) and "Do you accept bitcoin?" (0.378). The docs never mention the UK or bitcoin, so the reranker is unsure, yet the right answer is in the chunk. A 0.5 gate would answer "I don't know" to both. At **0.15** all real off-topic questions are stopped and 99% of answerable ones pass. "Nova X 2 release" (0.284) and "best Dell laptop" (0.457) pass the gate; the router and the answer-only-from-context prompt handle them in Phase 5.

Lesson: tune thresholds on the errors that matter, not on one number from 7 examples.

## Verified

- `make test-all`: 1397 passed (17 new retrieval tests, including integration tests on an empty knowledge base inside a rolled-back transaction).
- `make lint`: clean. Eval re-run from cache: 0 API calls.

## Concepts to know

- **RRF (Reciprocal Rank Fusion):** score = Σ 1/(60 + rank). Uses ranks, not scores, so cosine and `ts_rank` never need to be compared.
- **Cross-encoder reranker:** reads question and chunk together. Precise but slower, so it only re-orders ~20 candidates.
- **hit@k:** did a correct document appear in the top k? **MRR:** average of 1/rank of the first correct one (1.0 = always first).
- **Relevance gate:** grounding L1's first line: don't generate when even the best chunk is weak.
- **Eval caching:** key = hash of (model, question, candidate texts); changes to any of them trigger a fresh call.
