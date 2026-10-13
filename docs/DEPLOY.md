# Deploying VoltCart

Three pieces, each with a free tier: **Postgres + pgvector** (Neon), the **API** (Render, from `backend/Dockerfile`), and the **website** (Vercel, from `frontend/`). Any host that runs a Docker image and any Postgres 16 with pgvector 0.8+ work the same way.

```
Browser ──► Vercel (Next.js: chat, /widget, /admin) ──► Render (FastAPI, Docker) ──► Neon (Postgres + pgvector)
                                                              └─► Groq · Cohere · Langfuse
```

## 1. Database: Neon

1. Create a project (Postgres 16) at neon.tech and copy the connection details.
2. Nothing else to set up. The first migration runs `CREATE EXTENSION IF NOT EXISTS vector`, and the API applies migrations every time it starts.

## 2. API: Render (Web Service, Docker)

- **Root directory:** repository root. **Dockerfile path:** `backend/Dockerfile`. Health check path: `/health`.
- **Environment variables** (everything from `.env.example` that you use), at least:

| Variable | Value |
|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | From Neon (port 5432) |
| `GROQ_API_KEY`, `COHERE_API_KEY` | Your keys |
| `ADMIN_PASSWORD`, `JWT_SECRET` | A long password; `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `CORS_ORIGINS` | Your website's address, e.g. `https://voltcart-help.vercel.app` |
| `TRUSTED_PROXIES` | Your platform's proxy IPs, so rate limits see real visitors (otherwise every visitor shares the proxy's limit) |
| `LOG_FORMAT` | `json` |
| `LANGFUSE_*` | Optional, for tracing |

- **Load the data once** (Render shell, or locally with the Neon variables): `python -m scripts.seed` then `python -m scripts.ingest` (about 3 Cohere calls).
- **Uploaded documents:** the container's disk is temporary on most free tiers, so admin uploads disappear on redeploy. Either keep documents in `sample_data/docs/` in git (they're built into the image), or attach a persistent disk at `/app/sample_data/docs/uploads`.

## 3. Website: Vercel

- Import the repository; **root directory** `frontend`.
- **Environment variables:**
  - `NEXT_PUBLIC_API_URL` = the Render URL (built into the browser code, so redeploy after changing it).
  - `WIDGET_ALLOWED_PARENTS` = the sites allowed to embed the widget, space-separated (e.g. `https://voltcart.example`). Leaving it `*` lets any site frame the widget.
- **Embed the widget** on the store: `<script src="https://<your-vercel-app>/widget.js" async></script>`.

## Or everything on one machine (any VPS)

```bash
cp .env.example .env    # fill in keys, ADMIN_PASSWORD, JWT_SECRET, CORS_ORIGINS, PUBLIC_API_URL
make up                 # docker compose: postgres + api + web
make docker-seed && make docker-ingest
```

Put a reverse proxy with HTTPS (Caddy or nginx) in front of ports 3000 and 8000, and set `TRUSTED_PROXIES` to its address.

## Checklist before real customers

- [ ] HTTPS everywhere; `CORS_ORIGINS` and `WIDGET_ALLOWED_PARENTS` list only your sites
- [ ] `ADMIN_PASSWORD` and `JWT_SECRET` are long and random; `.env` never committed
- [ ] `TRUSTED_PROXIES` set (or rate limits treat all visitors as one)
- [ ] `make eval` passes against the deployed configuration (the models and `MIN_RELEVANCE` you actually use)
- [ ] Paid tiers or fallback providers: free tiers cap tokens per minute and per day, so expect slow answers and outages under real traffic
- [ ] Database backups (Neon has point-in-time restore); Langfuse tracing on to watch real conversations and 👎 feedback
