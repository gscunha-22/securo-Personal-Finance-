"""Private-instance policy, token encryption, and security headers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.models.user import User

_BOOTSTRAP_LOCK = 87451203
_current_request: ContextVar[Request | None] = ContextVar("securo_request", default=None)


def _fernet() -> Fernet:
    secret = get_settings().secret_key.get_secret_value().encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt stored credential") from exc


def sanitize_error(message: str) -> str:
    redacted = message
    for needle in ("Bearer ", "ya29.", "refresh_token", "client_secret"):
        if needle.lower() in redacted.lower():
            redacted = "A credential or token was removed from this error."
            break
    return redacted[:500]


async def owner_count(session: AsyncSession) -> int:
    result = await session.scalar(select(func.count()).select_from(User))
    return int(result or 0)


async def lock_instance_bootstrap(session: AsyncSession) -> None:
    """Serialize first-user creation. PostgreSQL advisory lock; no-op on SQLite."""
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BOOTSTRAP_LOCK})


async def registration_allowed(session: AsyncSession) -> bool:
    from app.services.admin_service import is_registration_enabled

    settings = get_settings()
    if settings.private_instance and await owner_count(session) >= 1:
        return False
    return await is_registration_enabled(session)


def content_disposition(disposition: str, filename: str) -> str:
    """RFC 5987 Content-Disposition with a sanitized ASCII fallback."""
    raw = (filename or "download").replace("\r", " ").replace("\n", " ").strip() or "download"
    fallback = re.sub(r'["\\]', "_", raw)
    fallback = "".join(ch if ch.isascii() else "_" for ch in fallback)[:80] or "download"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(raw)}"


def _frontend_is_local_http() -> bool:
    """Cookie Secure must stay off for loopback HTTP (localhost and 127.0.0.1)."""
    url = get_settings().frontend_url.lower()
    return (
        url.startswith("http://localhost")
        or url.startswith("http://127.0.0.1")
        or url.startswith("http://[::1]")
    )


def cookie_secure() -> bool:
    """HTTPS responses get Secure cookies, including the Vercel rewrite.

    ``FRONTEND_URL`` is the CORS origin. During handoff it may still be
    ``http://localhost:5173`` while Render is already HTTPS behind
    ``TRUSTED_PROXY_HOPS``. Prefer ``X-Forwarded-Proto`` when we trust the proxy.
    """
    request = _current_request.get()
    if request is not None:
        if get_settings().trusted_proxy_hops:
            forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
            if forwarded == "https":
                return True
            if forwarded == "http":
                return False
        if request.url.scheme == "https":
            return True
    return not _frontend_is_local_http()


def session_cookie_kwargs() -> dict:
    settings = get_settings()
    return {
        "key": "session",
        "httponly": True,
        "samesite": "lax",
        "secure": cookie_secure(),
        "path": "/",
        "max_age": settings.access_token_expire_minutes * 60,
    }


def attach_session_cookies(response: Response, token: str) -> Response:
    """Companion httpOnly session + readable CSRF cookie for cookie-based auth."""
    import secrets

    cookie = session_cookie_kwargs()
    csrf = csrf_cookie_kwargs()
    session_name = cookie.pop("key")
    csrf_name = csrf.pop("key")
    response.set_cookie(session_name, token, **cookie)
    response.set_cookie(csrf_name, secrets.token_urlsafe(32), **csrf)
    return response


def token_json_response(token: str) -> Response:
    from fastapi.responses import JSONResponse

    response = JSONResponse({"access_token": token, "token_type": "bearer"})
    return attach_session_cookies(response, token)


def csrf_cookie_kwargs() -> dict:
    settings = get_settings()
    return {
        "key": "csrf_token",
        "httponly": False,
        "samesite": "lax",
        "secure": cookie_secure(),
        "path": "/",
        "max_age": settings.access_token_expire_minutes * 60,
    }


def sign_csrf(token: str) -> str:
    secret = get_settings().secret_key.get_secret_value()
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    _CSRF_EXEMPT_PREFIXES = (
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/register",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/2fa/verify",
        "/api/auth/passkeys/authenticate",
        "/api/auth/passkeys/2fa",
        "/api/auth/oidc",
        "/api/setup/create-admin",
    )

    async def dispatch(self, request: Request, call_next):
        request_token = _current_request.set(request)
        try:
            started = datetime.now(timezone.utc)
            correlation = request.headers.get("x-correlation-id") or hashlib.sha1(
                f"{started.isoformat()}{request.url.path}".encode()
            ).hexdigest()[:16]
            request.state.correlation_id = correlation
            path = request.url.path
            exempt = any(path == prefix or path.startswith(prefix + "/") for prefix in self._CSRF_EXEMPT_PREFIXES)
            if (
                request.method in {"POST", "PATCH", "PUT", "DELETE"}
                and request.cookies.get("session")
                and not request.headers.get("authorization")
                and not exempt
            ):
                csrf_cookie = request.cookies.get("csrf_token")
                csrf_header = request.headers.get("x-csrf-token")
                if not (csrf_cookie and csrf_header and hmac.compare_digest(csrf_cookie, csrf_header)):
                    response = Response(
                        content='{"detail":"CSRF token mismatch"}',
                        media_type="application/json",
                        status_code=403,
                    )
                    response.headers["X-Correlation-Id"] = correlation
                    return response
            response: Response = await call_next(request)
            response.headers["X-Correlation-Id"] = correlation
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            )
            return response
        finally:
            _current_request.reset(request_token)
