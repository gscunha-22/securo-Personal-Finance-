from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings

settings = get_settings()


def _host(database_url: str) -> str:
    try:
        return (make_url(database_url).host or "").lower()
    except ArgumentError:
        return ""


def uses_neon_host(database_url: str) -> bool:
    """True for Neon Lakebase hostnames (pooled or direct)."""
    return _host(database_url).endswith(".neon.tech")


def uses_neon_pooler(database_url: str) -> bool:
    """PgBouncer transaction-pooler hosts include ``-pooler`` before the region."""
    host = _host(database_url)
    return "-pooler." in host or host.endswith("-pooler")


def neon_direct_url(database_url: str) -> str:
    """Strip the ``-pooler`` infix so Alembic talks to the compute, not PgBouncer."""
    url = make_url(database_url)
    host = url.host or ""
    marker = "-pooler."
    lowered = host.lower()
    idx = lowered.find(marker)
    if idx != -1:
        url = url.set(host=host[:idx] + host[idx + len("-pooler") :])
    return url.render_as_string(hide_password=False)


def alembic_database_url(cfg: Settings | None = None) -> str:
    """Prefer ``DATABASE_URL_DIRECT``; else derive a Neon direct host from the pooler URL."""
    cfg = cfg or get_settings()
    direct = cfg.database_url_direct.strip()
    if direct:
        return direct
    if uses_neon_pooler(cfg.database_url):
        return neon_direct_url(cfg.database_url)
    return cfg.database_url


def async_connect_args(database_url: str) -> dict[str, Any]:
    """asyncpg + Neon pooler cannot cache prepared statements.

    SSL is required for ``*.neon.tech``. Local Postgres and SQLite stay untouched.
    """
    args: dict[str, Any] = {}
    if uses_neon_host(database_url):
        args["ssl"] = True
    if uses_neon_pooler(database_url):
        args["statement_cache_size"] = 0
    return args


def create_engine_from_url(
    database_url: str,
    *,
    echo: bool = False,
    poolclass: Any = None,
    connect_args: dict[str, Any] | None = None,
    **kwargs: Any,
) -> AsyncEngine:
    merged = {**async_connect_args(database_url), **(connect_args or {})}
    engine_kwargs: dict[str, Any] = {"echo": echo, **kwargs}
    if merged:
        engine_kwargs["connect_args"] = merged
    if poolclass is not None:
        engine_kwargs["poolclass"] = poolclass
    if uses_neon_host(database_url):
        engine_kwargs.setdefault("pool_pre_ping", True)
        engine_kwargs.setdefault("pool_recycle", 300)
    return create_async_engine(database_url, **engine_kwargs)


def make_worker_session_maker(*, poolclass: Any = None):
    """Fresh engine + sessionmaker for a Celery worker event loop."""
    engine = create_engine_from_url(get_settings().database_url, poolclass=poolclass)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


engine = create_engine_from_url(settings.database_url, echo=settings.debug)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_async_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
