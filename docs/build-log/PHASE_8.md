# Phase 8 — API

**Goal:** the agent behind a web API: streamed chat, feedback, and admin endpoints for documents, tickets and conversations.

```
browser ──POST /chat──► FastAPI ──► worker thread: agent.stream() ──► queue ──► SSE events
                          │                                  └─► chat_turns (log) ─► admin panel
                          ├─ /feedback ──► feedback table + Langfuse score on that answer's trace
                          └─ /admin/* (JWT) ──► documents · re-index · tickets · conversations
```

## Endpoints

| Endpoint | Who | What |
|---|---|---|
| `POST /chat` | customer | `{message, session_id?}` → event stream: `start`, `token`…, `done` (or `error`) |
| `GET /chat/{session_id}/history` | customer | The conversation so far (redraw after a page reload) |
| `POST /feedback` | customer | 👍/👎 (+ comment) on one answer; sending again changes it |
| `POST /admin/login` | admin | Password → token valid 8 h |
| `GET/POST/DELETE /admin/documents` | admin | List; upload PDF/DOCX/HTML (searchable when the call returns); delete (file + chunks) |
| `POST /admin/reindex` | admin | Same as `make ingest` (incremental; `force` re-embeds all) |
| `GET/PATCH /admin/tickets` | admin | Handoff inbox, filter by status, open → in_progress → closed |
| `GET /admin/conversations`, `/admin/feedback` | admin | Every chat, 👎 count per chat, rated answers (the improvement to-do list) |

## What was built and why

| File | What it does | Why |
|---|---|---|
| `app/graph/agent.py` | `Agent.stream()`: yields the reply's tokens as the model writes them, then the final `Turn` | First words appear in ~1 s instead of waiting for the whole answer |
| `app/graph/builder.py` | `CitationStream` holds back a half-arrived `【1†L1-L7】` until it closes, then sends `[1]` | Citations arrive split across tokens; the customer never sees the raw form |
| `app/api/chat.py` | SSE endpoint; the turn runs in its own thread and feeds a queue | If the customer closes the tab mid-answer, the turn still finishes: memory and log stay consistent |
| `app/api/security.py` | Sliding-window rate limiter; admin JWT (HS256, 8 h, constant-time password check) | Free-tier quotas and brute-force protection; stateless admin sessions |
| `app/api/admin.py` | Upload: safe filename → parse a temporary copy → save → incremental ingest; on failure, put the folder back | A broken or malicious file never reaches the knowledge base |
| `app/db/models.py` | `chat_turns` (one row per Q&A) and `feedback` tables; migration `e52439a66bbf` | Checkpoints are the agent's memory (binary, internal); this is the readable record for admins |
| `app/observability.py` | One Langfuse handler per turn with **trace id = message id** | Feedback is attached to the exact trace it rates, with no lookup table |
| `app/main.py` | Agent built once at startup (connection pool for memory); CORS for our sites only | Several chats at once; other websites can't call the API from a browser |

## Security decisions

- **Session ids are made by the server** (32 random hex chars) and must match that format. The session id is the key to a conversation and the orders verified in it, so clients can't choose guessable ones.
- **One reply at a time per session** (409 otherwise): two at once would interleave the conversation's memory.
- **The `done` event hides internals.** Customers get the answer, citations and route. Admins also see the safety verdict, relevance score and grounding.
- **Feedback only from the conversation's own visitor:** both `session_id` and `message_id` must match.
- **Blocked messages report `route: "blocked"`.** The router still classifies them, but the UI should know they were blocked.
- **No tokens are streamed when `GROUNDING_CHECK` or `OUTPUT_GUARD` is on.** Those checks run after the answer is written; streaming would show a draft that might be rewritten or withheld.
- **Uploads:** the filename is reduced to safe characters (`../../etc/passwd.html` → `passwd.html`), only PDF/DOCX/HTML are accepted, up to 10 MB, and files must contain text. Catalog entries can't be deleted (they mirror the products table).

## Results

- `pytest`: **1566 passed** (67 new: SSE event order, fixed replies, errors, validation, 409/429/503, limiter window and thread safety, JWT expiry/forgery/`alg: none`, every admin route requires a token, CORS, upload names, streamed citations, tool calls not streamed; database tests for the log, history, feedback, tickets, upload/delete/re-index and rollback on failure).
- **Live (real Groq, 0 Cohere):**
  - First token at 2.2 s on smalltalk, words streamed one by one.
  - Order flow asked for the email.
  - Prompt attack blocked.
  - Card number removed, with a notice.
  - Feedback 204; admin without a token 401, with a token the conversations were listed.

## Lessons (bugs I made and fixed this phase)

- **Off-by-one in `Retry-After`:** `int(x) + 1` said 61 s for a 60 s wait. `math.ceil` is the right rounding, and a fake clock in the test caught it.
- **Postgres `now()` is the transaction's start time,** not the insert time, so rows inserted in one transaction tie and come back in random order. Tickets now sort by `created_at, id`, and chat turns get their time from Python.
- **Free-tier per-minute limits show up as latency:** one live message took 21 s because Groq's client waited 20 s and retried. Phase 12: a fallback provider instead of waiting.

## Concepts to know

- **SSE vs WebSocket:** SSE is one-way (server → browser) over plain HTTP, which is enough for streaming a reply and simpler to proxy. WebSockets are two-way, for things like typing indicators or live agents. Browsers' `EventSource` only does GET, so the UI will read the POST stream with `fetch`.
- **JWT:** a signed token (`header.payload.signature`). The server checks the signature and expiry without a database lookup. Fix the algorithm on decode, or an attacker can send `alg: none`.
- **CORS:** the browser asks the API "may this site call you?"; only our origins get yes. It protects browsers, not the API: rate limits and auth still apply to everyone.
- **Rate limiting (sliding window):** at most N requests in any 60 s. Kept in memory here (one server); several servers need a shared store like Redis.
- **Idempotent feedback:** sending the same rating twice updates one row instead of adding a second.
