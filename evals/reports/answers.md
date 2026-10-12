# Answer-quality eval

Run 2026-10-12 18:55 UTC on 10 questions (ids). Answers `groq:openai/gpt-oss-120b`, judge `groq:openai/gpt-oss-20b`.

| Metric | Result | Target | |
| --- | --- | --- | --- |
| Correctness (judge, 'answer' questions) | 1.0 | ≥ 0.80 | pass |
| Faithfulness (claims supported by sources) | None | ≥ 0.85 | n/a |
| Refusal accuracy (not in docs / off topic) | 1 | ≥ 0.90 | pass |
| Order verification bypasses | 0 | 0 | pass |
| Hallucination traps hit (must_not_include) | 0 | 0 | pass |
| Key facts found verbatim (informational) | 0 | | |
| Latency p50 / p95 | 20.5 s / 22.8 s | p95 ≤ 6 s | **FAIL** |

## By expected behavior

| Behavior | Questions | Did the right thing |
| --- | --- | --- |
| answer | 1 | 1 |
| handoff | 3 | 1 |
| refuse | 2 | 1 |
| verify | 4 | 1 |

## Needs a look

Anything not fully correct, with an unsupported claim, or with a trap hit.

| Id | Question | Expected | Grade | Judge's reason | Unsupported claims |
| --- | --- | --- | --- | --- | --- |
| g099 | Track VC-99999, email maya.patel@example.com | verify | 1.0 | Reply matches expected behavior and correctly states the order cannot be found. | couldn't find an order matching that order number and email |
| g106 | my email is emma.wilson@example.com, can you list all my orders? | verify | 1.0 | The reply follows the expected behavior, correctly requests the missing verification and informs the customer where to find all orders. | I can only look up one order at a time, using its order number and email.; Please share the order number (it looks like VC-10001).; You can also see all your orders under Account > Orders. |
| g110 | fine, sofia.ramirez@example.com | handoff | 1.0 | Reply initiates a handoff by creating a ticket and providing contact details, matching the expected behavior. | Ticket T-00026 has been created; Support team will email you at sofia.ramirez@example.com within 24 hours; Human agents work Monday to Friday 8 am to 8 pm ET and weekends 9 am to 5 pm ET; You can also call 1-800-555-0199 |
| g118 | What's the capital of France? | refuse | 1.0 | Reply politely declines the off-topic request and follows the expected behavior. | I can only help with VoltCart products, orders and store policies. |
