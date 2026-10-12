# Eval summary

Generated 2026-10-12 23:27 UTC from the latest results in `evals/reports/`. Gates: `evals/thresholds.toml`.

| Metric | Result | Target | Status | Measured |
| --- | --- | --- | --- | --- |
| Retrieval hit rate @5 | 0.9885 | ≥ 0.85 | pass | 2026-10-12 19:13 |
| Faithfulness (answer supported by sources) | 1.0 | ≥ 0.85 | pass | 2026-10-12 23:26 |
| Answer correctness (judge) | 1.0 | ≥ 0.8 | pass | 2026-10-12 23:26 |
| Refusal accuracy (unanswerable / off-topic) | — | ≥ 0.9 | not run | 2026-10-12 23:26 |
| Order verification bypasses | 0 | ≤ 0 | pass | 2026-10-12 23:26 |
| Routing accuracy | 1.0 | ≥ 0.9 | pass | 2026-10-12 23:27 |
| Guardrails: attacks handled (end to end) | 1.0 | ≥ 0.9 | pass | 2026-10-12 20:41 |
| Guardrails: harmless messages blocked | 0 | ≤ 0 | pass | 2026-10-12 20:41 |
| Guardrails: data leaks | 0 | ≤ 0 | pass | 2026-10-12 20:41 |

## Caveats

- Routing scored 7 of 122 questions (the rest hit rate limits: re-run make eval-routing).
- Answers were graded on 4 of the 122 golden questions (sample). Run make eval-answers args="--all" for the full set.
- Answers not scored (rate limits): ['g082', 'g006', 'g011', 'g051', 'g053', 'g050', 'g061', 'g078', 'g085', 'g049', 'g022', 'g042', 'g048', 'g035', 'g036', 'g028', 'g029', 'g088', 'g091', 'g086', 'g087', 'g089', 'g090', 'g092', 'g097', 'g098', 'g099', 'g106', 'g110', 'g093', 'g094', 'g117', 'g118', 'g111', 'g112', 'g114'].
