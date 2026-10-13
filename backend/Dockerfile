# VoltCart API. Build from the project root (it needs sample_data/):
#   docker build -f backend/Dockerfile -t voltcart-api .

FROM ghcr.io/astral-sh/uv:0.9.5 AS uv

FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app/backend
# Dependencies first: this layer is reused until pyproject.toml / uv.lock change
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
# The knowledge base sources (ingest reads them; admin uploads go under sample_data/docs/uploads)
COPY sample_data/ /app/sample_data/

# Never run as root inside the container
# (uploads/ exists in the image so a fresh volume mounted there is owned by the app user too)
RUN useradd --create-home --uid 10001 voltcart \
    && mkdir -p /app/sample_data/docs/uploads && chown -R voltcart /app
USER voltcart

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# Apply database migrations, then serve. Access logs come from our own middleware (JSON-ready)
# (Client IPs behind a proxy: set TRUSTED_PROXIES; see docs/DEPLOY.md)
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --no-proxy-headers"]
