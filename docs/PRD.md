# PRD — VoltCart AI Shopping & Support Assistant

| | |
|---|---|
| **Status** | Draft for approval |
| **Date** | 2026-10-10 |
| **Owner** | Project owner (you) |

## 1. Problem

Shoppers on an electronics store can't easily tell which product fits their needs ("which laptop for video editing under $1,200?") and have to dig through manuals, buying guides and policy pages. Support teams answer the same product, policy and order-status questions repeatedly.

## 2. Goal

A production-grade, customer-facing chatbot that:

1. **Helps customers learn about and choose products** (primary job), answering from manuals, buying guides and the product catalog, with citations.
2. **Answers policy questions** (shipping, returns, warranty, payment) from the help center.
3. **Looks up order status** only after verifying the customer (order ID + matching email).
4. **Hands off to a human** when it can't help or the customer asks.

It must run on **free tiers** now, and switch providers by configuration later.

## 3. Non-goals (v1)

- Customer accounts and logins (customers chat anonymously).
- Placing, cancelling or changing orders (read-only order status).
- Payments, voice, or image input.
- Multi-tenant (one store only).

## 4. Users

| User | Needs |
|---|---|
| **Shopper** (anonymous visitor) | Quick, accurate product advice and policy answers; trusts sources |
| **Existing customer** | Order status without waiting for support |
| **Support admin** | Manage knowledge documents, see handoff tickets, review conversations and feedback |

## 5. User stories

- As a shopper, I ask "best headphones for running under $150" and get 2–3 suitable products with reasons, prices and links.
- As a shopper, I compare two products and get a side-by-side answer.
- As a shopper, I ask a follow-up ("is it waterproof?") and the bot understands "it".
- As a shopper, I ask about returns and get the policy with a link to the source page.
- As a customer, I ask "where is my order?", the bot asks for my order ID and email, then shows status and tracking.
- As a customer, if I give a wrong email, the bot refuses to reveal the order and after 3 failed attempts offers human support.
- As a shopper, I click "talk to a human", leave my name, email and issue, and a ticket is created.
- As an admin, I upload a new PDF and the bot can answer from it within minutes; deleting a doc removes it from answers.
- As an admin, I see tickets, conversations and thumbs-down answers.

## 6. Functional requirements

| ID | Requirement |
|---|---|
| F1 | Ingest PDF, DOCX and HTML documents; chunk, embed and index them; re-index changed docs; remove deleted docs |
| F2 | Hybrid search (vector + keyword) with reranking and a relevance threshold |
| F3 | Answers cite their sources; no answer from weak context ("I'm not sure" + offer handoff) |
| F4 | Router classifies intent: product info, recommendation, order, handoff, small talk, off-topic |
| F5 | Product tools: search with filters (category, price, features), get details, compare |
| F6 | Order tool: status only after server-side verification of order ID + email; max 3 attempts |
| F7 | Handoff: collect contact + summary, create ticket with transcript |
| F8 | Conversation memory per session (follow-ups work) |
| F9 | Streaming chat UI with citations, product cards, feedback buttons, handoff form |
| F10 | Embeddable widget (one script tag) |
| F11 | Admin panel (password-protected): documents, re-index, tickets, conversations, feedback |
| F12 | Guardrails: PII redaction, injection/safety check (Llama Guard), off-topic refusal, grounding (L1 always; L2 + output check toggles) |
| F13 | Tracing of every request; user feedback recorded |
| F14 | Eval suite runnable with one command, with pass/fail thresholds |

## 7. Non-functional requirements

| Area | Target |
|---|---|
| Latency | First token ≤ 2 s, full answer p95 ≤ 6 s (free-tier providers) |
| Cost | $0/month in development |
| Portability | LLM, embedding and reranker providers changeable via `.env` |
| Security | No secrets in the browser; no free-form SQL; order data only after verification; rate limiting |
| Privacy | PII redacted in logs/traces |
| Reliability | Retries with backoff on provider rate limits; friendly error messages |
| Operability | Everything starts with `docker compose up`; health endpoint; structured logs |

## 8. Success metrics (eval thresholds)

| Metric | Target |
|---|---|
| Retrieval hit rate @5 | ≥ 0.85 |
| Faithfulness (answer supported by sources) | ≥ 0.85 |
| Answer correctness (judge) | ≥ 0.80 |
| Refusal accuracy (unanswerable / off-topic) | ≥ 0.90 |
| Routing accuracy | ≥ 0.90 |
| Guardrail block rate on attack set | ≥ 0.90 |
| Order verification bypasses | 0 |

## 9. Tech stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph + LangChain (integrations only) |
| LLM | Groq free tier: `llama-3.3-70b-versatile` (answers), `llama-3.1-8b-instant` (routing, rewriting, judging) |
| Safety model | Llama Guard on Groq |
| Embeddings / rerank | Cohere free trial key (Embed multilingual v3, Rerank) |
| Database | Postgres 16 + pgvector (Docker, port 5433) |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, uv |
| Frontend | Next.js + Tailwind + shadcn/ui |
| Observability | Langfuse Cloud (free tier) |
| Evals | pytest harness + LLM judge, results to Langfuse |
| Dev tools | Docker Desktop, pgAdmin 4, VS Code / Cursor, git |

## 10. Data

See [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md): 21 documents (8 PDF, 4 DOCX, 9 HTML) + products, customers, orders and shipments tables.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Free-tier rate limits (Groq, Cohere) | Small model for cheap steps, batching, backoff, provider swap via config |
| Cohere trial key not for commercial use | Interface allows swapping to a paid/open-source embedder |
| Hallucinated product facts | Grounding prompt, citations, relevance gate, faithfulness evals |
| Prompt injection exposing orders | Server-side verification; tools never trust the LLM's claims |

## 12. Open questions

- Golden Q&A set: you provide ~20 questions after Phase 2 (sample docs exist).
