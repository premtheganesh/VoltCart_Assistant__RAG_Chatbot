"""FastAPI entry point. Run with: make api"""

import logging

from fastapi import FastAPI

from app.api import health
from app.config import get_settings

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="VoltCart Assistant API", version="0.1.0")
app.include_router(health.router)
