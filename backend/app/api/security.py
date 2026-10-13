"""Rate limiting and admin authentication.

Customers are anonymous: they're limited per IP address. Admins log in with ADMIN_PASSWORD and
get a signed token (JWT) that every /admin request must send as `Authorization: Bearer <token>`.
"""

import hmac
import math
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

ALGORITHM = "HS256"


class RateLimiter:
    """At most `limit` hits per key in any `window` seconds (sliding window, in memory).

    In memory means per API process: fine for one server. With several, use Redis instead."""

    def __init__(self, limit: int, window: float = 60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Records a hit and returns 0 if allowed, else the seconds to wait."""
        now = self.clock()
        with self.lock:
            hits = self.hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] + self.window - now))
            hits.append(now)
            return 0

    def check(self, key: str) -> None:
        if wait := self.retry_after(key):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many messages. Please wait a moment and try again.",
                headers={"Retry-After": str(wait)},
            )


def client_ip(request: Request, trusted: set[str] | None = None) -> str:
    """The visitor's IP, for rate limits. Behind a proxy, the connection comes from the proxy:
    then the visitor is the right-most X-Forwarded-For entry that isn't one of our proxies.
    The header is only believed when the connection itself comes from a trusted proxy."""
    trusted = get_settings().trusted_proxy_list if trusted is None else trusted
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if peer not in trusted or not forwarded:
        return peer
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):  # proxies append, so the last untrusted address is the client
        if hop not in trusted:
            return hop
    return peer


# ---------- admin tokens ----------

_random_secret = secrets.token_urlsafe(32)


def _secret(settings: Settings) -> str:
    return settings.jwt_secret.get_secret_value() if settings.jwt_secret else _random_secret


def check_password(password: str, settings: Settings) -> bool:
    if settings.admin_password is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Admin login is disabled: set ADMIN_PASSWORD."
        )
    # Constant-time comparison: response time doesn't reveal how much of the password matched
    return hmac.compare_digest(
        password.encode(), settings.admin_password.get_secret_value().encode()
    )


def create_token(settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {"sub": "admin", "iat": now, "exp": now + timedelta(hours=settings.admin_token_hours)}
    return jwt.encode(claims, _secret(settings), algorithm=ALGORITHM)


def verify_token(token: str, settings: Settings) -> dict:
    """Checks the signature and expiry. The algorithm is fixed: a token can't pick its own."""
    return jwt.decode(
        token, _secret(settings), algorithms=[ALGORITHM], options={"require": ["exp"]}
    )


bearer = HTTPBearer(auto_error=False)


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Log in first.",
                            headers={"WWW-Authenticate": "Bearer"})  # fmt: skip
    try:
        return verify_token(credentials.credentials, settings)["sub"]
    except jwt.ExpiredSignatureError:
        detail = "Your session expired. Please log in again."
    except jwt.InvalidTokenError:
        detail = "Invalid token. Please log in again."
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail,
                        headers={"WWW-Authenticate": "Bearer"})  # fmt: skip


AdminUser = Annotated[str, Depends(require_admin)]
