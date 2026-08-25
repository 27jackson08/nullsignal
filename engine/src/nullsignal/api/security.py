"""Security response headers.

A decision-support tool for a public agency is exactly the kind of thing that
ends up embedded in an intranet portal or proxied behind something nobody
audits, so the defaults matter more than usual.

HSTS is emitted only over TLS. Sending it over plain HTTP is meaningless at
best -- browsers ignore it -- and actively harmful if a developer copies the
config to a host that cannot serve HTTPS, because the browser will then refuse
the only scheme that works.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# One year, and eligible for the preload list.
HSTS = "max-age=31536000; includeSubDomains; preload"

# This service answers with JSON and nothing else: no scripts, no frames, no
# embedded media. The policy says so rather than allowing anything by default.
API_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Content-Security-Policy": API_CONTENT_SECURITY_POLICY,
    # Nothing served here is public or cacheable by an intermediary: the
    # verdicts describe named neighbourhoods at a point in time.
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in BASE_HEADERS.items():
            response.headers.setdefault(header, value)
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response
