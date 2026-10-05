"""Origin guard: accept a request only when it carries the edge header we configured.

The public domain is served through a proxy that injects this header; the service's
own address is not meant to be used directly. The guard is inert unless both a token
is configured and enforcement is switched on, so tests and local runs are unaffected.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from app.config import settings

EDGE_HEADER = "x-edge-token"
# Liveness must stay reachable for the platform's own probe, which does not carry the header.
EXEMPT_PATHS: frozenset[str] = frozenset({"/health"})
FORBIDDEN_BODY = "Forbidden"

def edge_seen(request: Request) -> bool:
    """True when the request carries the configured origin header."""
    token = settings.edge_token
    if not token:
        return False
    return request.headers.get(EDGE_HEADER) == token

def edge_blocked(request: Request) -> bool:
    """True when enforcement is on and this request must be refused."""
    if not settings.edge_enforce or not settings.edge_token:
        return False
    if request.url.path in EXEMPT_PATHS:
        return False
    return not edge_seen(request)

async def edge_guard(request: Request, call_next):
    if edge_blocked(request):
        return PlainTextResponse(FORBIDDEN_BODY, status_code=403)
    return await call_next(request)
