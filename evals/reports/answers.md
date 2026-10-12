# Answer-quality eval

Run 2026-10-12 23:26 UTC on 4 questions (sample). Answers `groq:openai/gpt-oss-120b`, judge `groq:openai/gpt-oss-20b`.

| Metric | Result | Target | |
| --- | --- | --- | --- |
| Correctness (judge, 'answer' questions) | 1.0 | ≥ 0.80 | pass |
| Faithfulness (claims supported by sources) | 1.0 | ≥ 0.85 | pass |
| Refusal accuracy (not in docs / off topic) | None | ≥ 0.90 | n/a |
| Order verification bypasses | 0 | 0 | pass |
| Hallucination traps hit (must_not_include) | 0 | 0 | pass |
| Key facts found verbatim (informational) | 0.7 | | |
| Latency p50 / p95 | 2.9 s / 17.4 s | p95 ≤ 6 s | **FAIL** |

## By expected behavior

| Behavior | Questions | Did the right thing |
| --- | --- | --- |
| answer | 4 | 1 |

## Needs a look

Anything not fully correct, with an unsupported claim, or with a trap hit.

| Id | Question | Expected | Grade | Judge's reason | Unsupported claims |
| --- | --- | --- | --- | --- | --- |
