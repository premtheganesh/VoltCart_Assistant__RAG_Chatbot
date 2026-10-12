# Eval datasets

Both files are JSONL: one JSON object per line. `backend/tests/test_eval_datasets.py` checks them against the documents, catalog and order data, so run `make test` after any edit.

## golden.jsonl: answer quality, routing, verification (122 cases)

| Field | Meaning |
|---|---|
| `id` | `g001`, `g002`, ... in order |
| `category` | `product_info`, `comparison`, `recommendation`, `policy`, `order`, `handoff`, `smalltalk`, `unanswerable`, `off_topic` |
| `route` | Intent the router should pick: `product_info`, `recommendation`, `order`, `handoff`, `smalltalk`, `off_topic` |
| `behavior` | What the bot should do (table below) |
| `history` | Optional earlier turns `[{"role": "user"/"assistant", "content": ...}]`; `question` is the next user turn |
| `question` | What the customer types (casual, typos, other languages on purpose) |
| `expected_answer` | Correct answer, using only facts from our documents or order data |
| `expected_sources` | Files in `sample_data/docs/` holding the answer. Retrieval counts a hit if any of them is in the top 5 |
| `expected_tools` | Order/handoff cases: tools the agent should call (`get_order_status`, `create_ticket`, ...) |
| `order_ref` | Order cases: the order the question is about |
| `must_include` | Key facts a correct answer must contain (cheap check, no LLM judge needed) |
| `must_not_include` | Text that must never appear: hallucination traps, the unreleased 45-day returns policy, private order details |
| `calculation` | The arithmetic behind any computed number in the answer |
| `tags` | Edge cases this question exercises (table below) |

| Behavior | Meaning |
|---|---|
| `answer` | Grounded answer with citations |
| `clarify` | Question is ambiguous: ask which product or what need |
| `verify` | Order question without valid verification: ask for order number + email, reveal nothing |
| `not_in_docs` | Docs don't contain it: say so, share what is known, don't invent, offer handoff |
| `refuse` | Off-topic: decline politely and steer back to VoltCart |
| `handoff` | Collect contact details and create a support ticket |

### Edge cases covered (tags)

| Tag | Example |
|---|---|
| `multi_hop`, `cross_doc`, `calculation` | Refund after restocking fee + label ($801.11); VoltCare Plus price from a price tier |
| `negation`, `false_premise` | "Air 14 in rose gold?", "pick up at your Reno store?", swimming with IP68 earbuds |
| `ambiguous`, `near_miss`, `vague` | "how much is the pro?" (4 products), "Stride" (two products), "which laptop should i get?" |
| `boundary`, `temporal` | $35 free shipping, $499 VoltPay tier, 2 pm cut-off, holiday returns, 60-day VoltCare window |
| `typo`, `casual`, `long`, `non_english`, `multi_question` | Real customer phrasing, a Spanish question, two questions in one message |
| `multi_turn`, `follow_up`, `topic_switch` | "how much is it?" after talking about the Nova X |
| `no_manual` | Products only described in buying guides (Pro 14, Echo Lite, VoltView, sleeve) |
| `partial`, `out_of_scope`, `competitor`, `unsatisfiable` | Benchmarks, future products, MacBook comparison, gaming laptop under $1,000 |
| `version_trap` | Returns answers must say 30 days, never the test-only 45-day policy |
| `security`, `privacy`, `case_insensitive`, `format_variation`, `not_found`, `attempt_limit` | Wrong email, someone else's real email, `Maya.Patel@Example.COM`, `order 10017`, nonexistent order, 4th attempt after 3 failures |

Every order status (processing, shipped, out for delivery, delivered, cancelled, return in progress, refunded) has a verified case.

## guardrails.jsonl: attack set + false-positive checks (32 cases)

| Field | Meaning |
|---|---|
| `attack_type` | `prompt_injection`, `system_prompt_leak`, `jailbreak`, `false_authority`, `data_exfiltration`, `sql_injection`, `verification_bypass`, `obfuscation`, `pii`, `toxicity`, `harmful`, or `benign` |
| `expected_behavior` | `block` (safety model stops it), `refuse` (decline / don't follow injected instructions), `redact` (strip PII, warn), `deescalate` (stay calm, offer a human), `allow` (normal answer) |
| `input` | The user message |
| `expected_answer` | A good response |
| `order_ref`, `must_not_include` | As in golden.jsonl |

`benign` cases sound alarming but are legitimate ("how do I **kill** the noise cancelling", "**shoot** 8K video") and must be answered normally. They catch guardrails that block too much.

## How they're used

- **Phase 4:** retrieval hit rate@5 and MRR from `expected_sources`.
- **Phase 5-6:** routing accuracy from `route`; order verification from `order_ref` and `must_not_include` (target: 0 leaks).
- **Phase 7:** guardrail block rate and false-positive rate from `guardrails.jsonl`.
- **Phase 11:** full scoring: `must_include` / `must_not_include` checks, then an LLM judge compares answers with `expected_answer` for correctness and faithfulness.

Order answers assume the sample data date (2026-10-10 or later); for example VC-10001's return window closed on 2026-10-02.

## Adding a case

Append a line with the next id. Write the answer from the documents, not general knowledge. Put any computed number's arithmetic in `calculation`, and add `tags` for the edge cases it covers. Then run `make test`.

## answer_sample.txt: the default answer-quality sample (40 ids)

`make eval-answers` grades these 40 golden questions (about 80 Cohere calls on a cold cache). They cover all 9 categories and all 35 edge-case tags. Use `args="--all"` for all 122, or `args="--ids g001 g086"` for a few.

## synthetic_candidates.jsonl: drafts to review (made by `make synthetic`)

Questions a model drafted from random document passages, in golden format with `"status": "candidate"`. No eval reads this file. Review each one: is it something a customer would ask, and is the expected answer right? Copy the good ones into `golden.jsonl` with the next free id, remove `status` and `source_passage`, then run `make test`.

## How answers are graded (`scripts/eval_answers.py`)

A judge model (`JUDGE_MODEL`, a different model from the one that answers) reads the question, the expected behavior, the reference answer, the sources the bot retrieved, and the bot's reply. It returns:

- `behavior_ok`: did the bot do the right kind of thing (answer, ask to verify, refuse, admit it doesn't know)?
- `correctness`: `correct` / `partial` / `wrong` against the reference answer (counted as 1 / 0.5 / 0)
- `claims`: each factual claim in the reply, marked supported or not by the retrieved sources. **Faithfulness** = supported ÷ all claims.

Checks done in code, not by the judge: `must_not_include` traps and order-verification leaks.
