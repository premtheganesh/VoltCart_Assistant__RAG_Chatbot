# Phase 6 — Tools: catalog, verified orders, human handoff

**Goal:** answer what documents can't (live prices, stock, "under $150", side-by-side specs), look up orders safely, and hand customers to a human with a ticket.

```
router ─┬─ product_info / recommendation ─► retrieve docs ─► answer ⇄ catalog tools (≤ 3 rounds)
        ├─ order ─► number? ─► email? ─► verify in code ─► answer from that order + policy docs
        │            (3 failures in a conversation ─► locked, offer a human)
        └─ handoff ─► contact details? ─► create ticket in the database
```

## What was built and why

| File | What it does | Why |
|---|---|---|
| `app/tools/products.py` | `search_products` (category, price range, keywords in name/specs/tags, in stock, sort), `get_product` (SKU, exact or partial name), `compare_products` | Exact, live data from the database. The LLM only picks arguments; it never writes SQL |
| `app/tools/orders.py` | `verify_order(number, email)`, order-number and email parsing | Returns an order only if both match. Wrong email and unknown order return the same `None`. No customer name or email in the result |
| `app/tools/tickets.py` + `tickets` table (migration) | `create_ticket` with name, email, summary, reason, transcript, status | The admin inbox (Phase 10) reads these |
| `app/graph/builder.py` | Tool loop in the answer node; `order` and `handoff` nodes | Tool results become numbered sources, so they're cited like documents |
| `app/graph/state.py` | Remembers per conversation: verified orders, failed attempts, pending order number, what the bot just asked, handoff reason, ticket | Multi-turn flows ("VC-10003" → "and the email?" → "sofia@...") |
| `app/graph/prompts.py` | Order answer prompt, contact extraction prompt, fixed replies for every verification step | Every security-relevant reply is fixed text, not LLM output |

## Security rules (enforced in code, tested)

1. No order data without the matching order number **and** email (case and spaces ignored).
2. "Wrong email" and "no such order" get the identical reply, so order numbers can't be probed.
3. Three failed attempts lock order lookups for the conversation, **even with the right email afterwards**; the bot offers a human instead.
4. Verifying one order doesn't unlock another; a verified order needs no re-entry for follow-ups.
5. An email alone never lists orders.
6. The LLM sees only the verified order, never other customers' data.
7. Tickets store only contact details the customer actually typed: an email or name the model "extracted" but nobody typed is discarded.

## Key choices

- **State instead of `interrupt()`.** The plan said interrupt/resume. A chat already pauses between messages, so the order node simply remembers what it asked (`awaiting`, `pending_order`). `interrupt()` suits pausing mid-run for an outside decision (e.g. a human approving a refund), which we don't need yet.
- **Answering our own question skips the router.** If the bot asked for an email and the reply contains one, it goes straight to the order or handoff node: faster, and immune to a misrouted "sofia@example.com".
- **Tools on both product routes.** Most product questions use no tool (one LLM call). The model calls tools for budgets, stock and comparisons. After 3 tool rounds it must answer (`tool_choice="none"`).
- **Live catalog beats documents.** Prompt: prefer tool prices and stock when a document differs.
- **No invented links.** A real-model run produced a made-up FedEx tracking URL; both answer prompts now forbid links or details not in the data (re-checked: 0 of 3 runs).

## Fixes from your real chats

| What happened | Fix |
|---|---|
| `--debug` crashed on catalog sources (no score) | Shown as `[ live]`; test added |
| Router model out of daily tokens: chat hung in Groq's client retry loop | Small model fails fast (`max_retries=0`) and every small-model job (router, small talk, contact extraction) **falls back to the main model** via LangChain `with_fallbacks`; verified: 1.7-2.9 s instead of hanging |
| After the customer sent only their email, the policy search used the email as the query | The original question ("track order VC-10003") is kept (`pending_question`) and used for the search |
| Debug view said "no retrieval" for order answers | Shows the policy pages' top score |
| Trace-export and retry notices printed inside the chat | Sent to the log only |
| A "refuse delivery" answer added steps not in the docs ("arrange a replacement") | Open: grounding check (L2) and faithfulness eval in Phases 7 and 11 |
| 40 s turns | Network blips and Groq's free-tier 8,000 tokens/minute limit (an answer with sources is ~3,000 tokens). Streaming (Phase 8) and fallbacks/paid tier (Phase 12) |

## Verified

- `make test`: 1413 passed. On a temporary database: all 1453 incl. 13 new tool tests on the real seeded data (SQL-injection attempts find nothing; verified orders contain no customer identity) and the migration's downgrade + upgrade.
- 23 new graph tests with fakes cover every rule above, the tool loop (citable tool sources, errors reported to the model, 3-round cap) and ticket reasons (`customer_request`, `no_answer`, `verification_locked`).
- Real models (Groq, no Cohere, temporary database): catalog search with live stock, a camera comparison table, the full order flow including a wrong email then the right one, "can I still cancel it?", and a ticket created with an AI summary.

## Concepts to know

- **Tool calling:** the model returns a request (`search_products(category="audio", max_price=150)`) instead of text; our code runs it and sends the result back; the model then answers.
- **Authorization in code:** security decisions are never delegated to the LLM. It phrases answers; code decides what data it may see.
- **Enumeration attack:** probing which records exist from different error messages. Prevented with one identical reply.
- **Rate limiting attempts:** a small attempt cap blocks guessing emails for a known order number.
