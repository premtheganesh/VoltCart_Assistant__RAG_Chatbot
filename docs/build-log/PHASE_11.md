# Phase 11 — Full evals

**Goal:** measure answer quality, not just retrieval, and check every PRD target with one command.

```
make eval  =  eval-retrieval → eval-routing → eval-guardrails (full) → eval-answers → eval-summary
              (each cached: a re-run only redoes what changed)           checks evals/thresholds.toml
```

## What was built and why

| Piece | What it does | Why |
|---|---|---|
| `scripts/eval_answers.py` (`make eval-answers`) | Runs the whole bot on golden questions; a **judge model** grades each reply: right kind of response (`behavior_ok`), `correct` / `partial` / `wrong` against the reference, and each factual claim supported or not by the retrieved sources (**faithfulness**). Traps and order-detail leaks are checked in code | Retrieval hit rate says the right page was found, not that the answer was right |
| Judge = `gpt-oss-20b` (`JUDGE_MODEL`) | A different model from the one answering, with strict JSON-schema output | No grading your own homework, and its own free-tier quota |
| `evals/datasets/answer_sample.txt` | 40 of 122 questions, all 9 categories and all 35 edge-case tags | About 80 Cohere calls instead of about 250; `args="--all"` runs everything |
| `evals/thresholds.toml` + `scripts/eval_all.py` | The 9 PRD gates in one file; `make eval-summary` writes `evals/reports/summary.md` and fails if a gate fails | One command answers "is it good enough?" (ready for CI) |
| `scripts/generate_synthetic.py` (`make synthetic`) | Drafts new questions from random passages, for a human to review | Grows the test set without letting a model write its own exam unchecked |
| Langfuse | Each graded answer's trace gets `eval_correctness` / `eval_faithfulness` scores | See a bad grade next to the full trace of what the bot did |

## Results

Last **complete** run of the 40-question sample (before the final router fix below):

| PRD gate | Result | Target |
|---|---|---|
| Retrieval hit@5 | 0.99 | ≥ 0.85 ✅ |
| Faithfulness | 0.99 | ≥ 0.85 ✅ |
| Answer correctness | 0.85 | ≥ 0.80 ✅ |
| Refusal accuracy | 1.00 | ≥ 0.90 ✅ |
| Routing accuracy | 0.99 | ≥ 0.90 ✅ |
| Guardrails: attacks handled / harmless blocked / leaks | 24/24, 0/8, 0 | ≥ 0.90, 0, 0 ✅ |
| Order verification bypasses | 0 | 0 ✅ |
| Latency p95 (not a gate) | about 23 s | ≤ 6 s ❌ free-tier rate limits; Phase 12 |

**Still to do:** re-measure after the final router-prompt change (product names), once Groq's daily quota refills. Run `make eval`; finished results are cached.

## What the evals caught (and what was fixed)

1. **The reranker hung (Cohere `rerank-v3.5` stopped responding).** No timeout, and timeouts were retried, so one question waited 30+ minutes. Fixed in production code:
   - 8 s timeout per call and about 12 s of retries in total.
   - If reranking fails, the bot falls back to hybrid search order (still answering only from sources).
   - A **circuit breaker** skips the reranker for 5 minutes after a failure: 41 s → 22 s for the first question during an outage, then 4 s.
   - Switched `.env` to `rerank-multilingual-v3.0` for now. It has the same hit@5 (0.99) and MRR (0.93), but scores on a different scale, so `MIN_RELEVANCE` was re-tuned 0.15 → **0.10** (gate accuracy 0.99).
2. **The router misrouted gaming questions to off-topic** ("turbo mode is greyed out on my gaming laptop", "is the Gamer 15 good for shooter games?"). The prompt now says the Gamer 15 is a gaming laptop and that device problems and activities are product questions. Harmless messages blocked: 2/8 → 0/8.
3. **The backup router failed when the small model ran out of daily quota.** It sent "factory reset my Pulse ANC" off-topic because the prompt named product *families*, not products. The router prompt now lists every product name: backup router 10/10.
4. **A refund calculation forgot the $7.99 return label.** The answer prompt now says: when working out money, apply every fee and deduction from the sources, and show the steps.
5. **The judge was miscalibrated** (it called incomplete answers "wrong behavior", and penalized recommending alternatives). The rubric now separates *kind of response* from *completeness*. It was checked by reading every failed answer, not by aiming for a number.
6. **Evals retried daily quotas for hours.** Per-minute limits are worth waiting out; daily ones aren't. Evals now stop within seconds with "Daily quota used up … re-run after it resets", and keep what finished.

## Lessons

- **Read the failures, not just the score.** Of the first 4 "wrong" answers, 2 were bot bugs and 2 were judge bugs. Tuning the bot to a miscalibrated judge makes it worse.
- **Evals find production bugs.** The reranker hang and the weak backup router would have hit real customers. Neither was visible in unit tests.
- **Free tiers cap eval speed:** about 30 s per question, and 200k tokens per model per day. Caching and a fixed sample make it workable.

## Concepts to know

- **LLM-as-judge:** a model grades answers against a rubric and a reference. Cheap and scalable, but it needs calibration (read its verdicts) and should be a different model from the one being graded.
- **Faithfulness vs. correctness:** faithful = every claim comes from the sources (no hallucination). Correct = it matches the right answer. An answer can be faithful but wrong (it quoted the wrong page), or correct but unfaithful (right by luck, from training data).
- **Quality gates:** fixed thresholds that fail the build (CI) when quality drops, the same way failing unit tests do.
- **Circuit breaker:** after a dependency fails, stop calling it for a while and use a fallback, so every request doesn't pay the timeout.
