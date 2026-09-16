"""Private-instance policy, token encryption, and security headers."""
from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.models.user import User


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


async def registration_allowed(session: AsyncSession) -> bool:
    from app.services.admin_service import is_registration_enabled

    settings = get_settings()
    if settings.private_instance and await owner_count(session) >= 1:
        return False
    return await is_registration_enabled(session)


def session_cookie_kwargs() -> dict:
    settings = get_settings()
    secure = not settings.frontend_url.startswith("http://localhost")
    return {
        "key": "session",
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
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
    secure = not settings.frontend_url.startswith("http://localhost")
    return {
        "key": "csrf_token",
        "httponly": False,
        "samesite": "lax",
        "secure": secure,
        "path": "/",
        "max_age": settings.access_token_expire_minutes * 60,
    }


def sign_csrf(token: str) -> str:
    secret = get_settings().secret_key.get_secret_value()
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = datetime.now(timezone.utc)
        correlation = request.headers.get("x-correlation-id") or hashlib.sha1(
            f"{started.isoformat()}{request.url.path}".encode()
        ).hexdigest()[:16]
        request.state.correlation_id = correlation
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.cookies.get("session"):
            if not request.headers.get("authorization"):
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
