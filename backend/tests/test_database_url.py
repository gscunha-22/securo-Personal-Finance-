from pathlib import Path

from sqlalchemy.engine.url import make_url

from app.core.config import Settings
from app.core.database import (
    alembic_database_url,
    async_connect_args,
    neon_direct_url,
    uses_neon_host,
    uses_neon_pooler,
)

POOLED = "postgresql+asyncpg://u:p@ep-abc-pooler.us-east-2.aws.neon.tech/neondb"
DIRECT = "postgresql+asyncpg://u:p@ep-abc.us-east-2.aws.neon.tech/neondb"
LOCAL = "postgresql+asyncpg://postgres:postgres@localhost:5432/securo"
SQLITE = "sqlite+aiosqlite:///:memory:"
REPO_ROOT = Path(__file__).resolve().parents[2]


def test_detects_neon_pooler_and_direct_hosts():
    assert uses_neon_host(POOLED)
    assert uses_neon_host(DIRECT)
    assert uses_neon_pooler(POOLED)
    assert not uses_neon_pooler(DIRECT)
    assert not uses_neon_host(LOCAL)
    assert not uses_neon_pooler(LOCAL)
    assert not uses_neon_host(SQLITE)
    assert not uses_neon_pooler(SQLITE)


def test_pooler_connect_args_disable_prepared_statements():
    pooled = async_connect_args(POOLED)
    assert pooled["ssl"] is True
    assert pooled["statement_cache_size"] == 0

    direct = async_connect_args(DIRECT)
    assert direct == {"ssl": True}

    assert async_connect_args(LOCAL) == {}
    assert async_connect_args(SQLITE) == {}


def test_neon_direct_url_strips_pooler_infix():
    derived = neon_direct_url(POOLED)
    assert make_url(derived).host == "ep-abc.us-east-2.aws.neon.tech"
    assert make_url(derived).password == "p"
    unchanged = neon_direct_url(DIRECT)
    assert make_url(unchanged).host == "ep-abc.us-east-2.aws.neon.tech"


def test_alembic_url_prefers_explicit_direct(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    settings = Settings(
        database_url=POOLED,
        database_url_direct=DIRECT,
        _env_file=None,
        _secrets_dir=str(secrets),
    )
    assert alembic_database_url(settings) == DIRECT


def test_alembic_url_derives_direct_from_pooler(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    settings = Settings(
        database_url=POOLED,
        database_url_direct="",
        _env_file=None,
        _secrets_dir=str(secrets),
    )
    derived = alembic_database_url(settings)
    assert make_url(derived).host == "ep-abc.us-east-2.aws.neon.tech"
    assert "pooler" not in (make_url(derived).host or "")


def test_alembic_url_keeps_local_postgres(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    settings = Settings(
        database_url=LOCAL,
        database_url_direct="",
        _env_file=None,
        _secrets_dir=str(secrets),
    )
    assert alembic_database_url(settings) == LOCAL


def test_vercel_spa_rewrites_api_to_persistent_origin():
    source = (REPO_ROOT / "frontend" / "vercel.ts").read_text(encoding="utf-8")
    assert "API_ORIGIN" in source
    assert "/api/:path*" in source
    assert "connect-src 'self'" in source
    assert "index.html" in source
    assert "throw new Error" in source
    assert 'framework: "vite"' in source
    assert "nextjs" not in source.lower()
    assert not (REPO_ROOT / "frontend" / "vercel.json").exists()
