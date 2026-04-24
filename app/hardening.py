from __future__ import annotations

import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse, Response

from app.config import settings


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
STATEFUL_BROWSER_PREFIXES = ("/app", "/logout")
AUTH_PREFIXES = ("/login", "/auth")
API_PREFIXES = ("/api/workspaces",)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _host_without_port(value: str) -> str:
    return value.split(":", 1)[0].lower()


def _same_origin(request: Request, value: str) -> bool:
    origin = urlparse(value)
    if not origin.hostname:
        return False
    return origin.hostname.lower() == _host_without_port(request.headers.get("host", ""))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        csp = [
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: https:",
            "connect-src 'self'",
        ]
        if settings.base_url.startswith("https://"):
            csp.append("upgrade-insecure-requests")
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault("Content-Security-Policy", "; ".join(csp))
        if request.url.path.startswith(("/app", "/api/workspaces")):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        else:
            response.headers.setdefault("Cache-Control", "public, max-age=120")
        return response


class RequestGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        blocked = self._validate_host(request) or self._validate_body_size(request) or self._validate_origin(request)
        if blocked:
            return blocked
        limited = self._rate_limit(request)
        if limited:
            return limited
        return await call_next(request)

    def _validate_host(self, request: Request) -> Response | None:
        host = _host_without_port(request.headers.get("host", ""))
        if host not in settings.host_allowlist():
            return PlainTextResponse("Invalid host", status_code=400)
        return None

    def _validate_body_size(self, request: Request) -> Response | None:
        content_length = request.headers.get("content-length")
        try:
            size = int(content_length) if content_length else 0
        except ValueError:
            return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        if size > settings.max_request_bytes:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return None

    def _validate_origin(self, request: Request) -> Response | None:
        if request.method in SAFE_METHODS or not request.url.path.startswith(STATEFUL_BROWSER_PREFIXES):
            return None
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        if origin and not _same_origin(request, origin):
            return PlainTextResponse("Cross-origin form submission blocked", status_code=403)
        if not origin and referer and not _same_origin(request, referer):
            return PlainTextResponse("Cross-origin form submission blocked", status_code=403)
        return None

    def _rate_limit(self, request: Request) -> Response | None:
        limit = 0
        if request.url.path.startswith(AUTH_PREFIXES):
            limit = settings.auth_rate_limit_per_minute
        elif request.url.path.startswith(API_PREFIXES):
            limit = settings.api_rate_limit_per_minute
        if limit <= 0:
            return None

        now = time.monotonic()
        route_scope = "/".join(part for part in request.url.path.split("/")[:4] if part)
        bucket_key = f"{_client_ip(request)}:{route_scope}"
        bucket = self._buckets[bucket_key]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= limit:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
        bucket.append(now)
        return None
