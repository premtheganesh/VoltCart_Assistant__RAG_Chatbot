# Phase 10 — Widget + admin panel

**Goal:** put the chat on any website with one line, and give the support team a panel for tickets, conversations, feedback and documents.

```
Any website ── <script src=".../widget.js"> ──► chat button (Shadow DOM) ──► iframe: /widget ──► API
Support team ── /admin (password → token) ──► Tickets · Conversations · Feedback · Documents
```

## What was built and why

| Piece | What it does | Why |
|---|---|---|
| `public/widget.js` | Draws a chat button in the corner and opens `/widget` in an iframe on first click | **iframe:** the host page's CSS and scripts can't reach the chat, and the chat calls the API from our own origin, so CORS stays strict. **Shadow DOM:** the host's CSS can't restyle the button. **Lazy:** the iframe loads only when opened, so the store's page isn't slowed down |
| `/widget` page | The same chat in a compact layout, with a close button that sends `postMessage` to the host | `widget.js` only accepts that message from our own origin |
| `next.config.ts` headers | `/widget` may be framed (`WIDGET_ALLOWED_PARENTS`, `*` in dev); every other page sends `X-Frame-Options: DENY` and `frame-ancestors 'none'` | **Clickjacking:** an attacker could load our admin in an invisible frame and trick a click. Only the widget is meant to be framed |
| `/admin/*` pages | Login; **Tickets** (filter by status, chat transcript, change status, reply by email); **Conversations** (every turn with route, relevance, latency, safety, rating); **Feedback** (👎 to-do list); **Documents** (upload by drag and drop, delete, re-index) | Everything `docs/PRD.md` asks of the admin, on the API from Phase 8 |
| `lib/admin-api.ts` | Token in `sessionStorage`, sent as `Authorization: Bearer`; any 401 sends the admin back to login | A header token isn't sent automatically like a cookie, so other sites can't use it (no CSRF). It's gone when the tab closes. The API checks the token on every call: the page-side redirect is only for convenience |
| `sample_data/widget-demo/` + `make widget-demo` | A fake store page on another port (8080) that embeds the widget, with deliberately hostile CSS | Proves cross-site embedding and isolation |

## Results

- **Frontend:** 36 unit tests (+9 admin client: token storage, 401 → logged out, errors, multipart upload, 204, API down, "time ago"). `tsc` and `next build` clean.
- **Headless Chrome, end to end** (real Groq, fake embeddings, 0 Cohere):
  - The widget on the demo store (another origin): the button stays ink-colored despite the host's `button {background: hotpink !important}`, and no iframe loads until the first click.
  - Answered in the widget; the contact form created **T-00001**; the chat's own close button closed the panel.
  - **The ticket appeared in the admin inbox** with its transcript. Closing it moved it to the Closed tab.
  - **Uploaded `gift-cards.html`** (1 added, 2 chunks) and asked "Do gift cards expire?": answered from the new doc, cited as [1]. **Deleted it** and asked again: "I don't have information…", no sources.
  - 👎 with a comment showed up under Feedback, then the conversation detail. After logging out, the admin pages require login again.
  - Headers: `/` and `/admin` refuse to be framed, `/widget` allows it, and admin pages are `noindex`.

## Lessons

- **Stale generated types:** `tsc` failed with "Route does not satisfy '/'" because an earlier `next dev` run had left a route list from before the admin pages existed. `npm run typecheck` now clears and regenerates route types first.
- **Test the hostile case:** the demo page attacks the widget with `!important` styles. A widget that only works on friendly pages breaks on real ones.

## Concepts to know

- **iframe vs. script-injected widget:** many chat widgets inject their HTML straight into the host page. That's simpler, but every host's CSS and JavaScript can then interfere with it, and API calls come from the host's origin. An iframe trades a little layout flexibility for isolation.
- **Same-origin policy and `postMessage`:** the host page and the iframe can't read each other. `postMessage` is the controlled channel, and the receiver must check `event.origin`.
- **Clickjacking:** framing a site invisibly and tricking clicks. Defended with `X-Frame-Options` / CSP `frame-ancestors`.
- **Token in a header vs. a cookie:** browsers attach cookies automatically, even to requests started by other sites (CSRF risk). Headers must be added by our own code.
