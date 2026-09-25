import os
import subprocess
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


def test_backup_script_derives_direct_url_for_neon_pooler(tmp_path):
    calls = tmp_path / "pg_dump_calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = bin_dir / "pg_dump"
    docker = bin_dir / "docker"
    pg_dump.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$1\" >> \"$PG_DUMP_CALLS\"\n"
        "printf 'ok'\n",
        encoding="utf-8",
    )
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"compose\" ] && [ \"$2\" = \"ps\" ]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    pg_dump.chmod(0o755)
    docker.chmod(0o755)

    env = os.environ.copy()
    env["DATABASE_URL"] = (
        "******ep-abc-pooler.us-east-2.aws.neon.tech/neondb?ssl=require"
    )
    env.pop("DATABASE_URL_DIRECT", None)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PG_DUMP_CALLS"] = str(calls)

    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "backup-instance.sh"), str(tmp_path / "backup")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    dumped_urls = calls.read_text(encoding="utf-8").splitlines()
    assert len(dumped_urls) == 2
    assert all("-pooler" not in url for url in dumped_urls)
    assert all("ep-abc.us-east-2.aws.neon.tech" in url for url in dumped_urls)


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


def test_sigv4_headers_include_signed_headers_and_signature():
    from app.providers.s3_storage import presigned_get_url, sigv4_headers

    headers = sigv4_headers(
        "PUT",
        "https://bucket.s3.us-east-2.amazonaws.com/key",
        access_key="AKIATEST",
        secret_key="secret",
        region="us-east-2",
        extra_headers={"Content-Type": "text/plain"},
        body=b"hello",
        amz_date="20260101T000000Z",
    )
    auth = headers["Authorization"]
    assert "SignedHeaders=" in auth
    assert "Signature=" in auth
    assert "Credential=AKIATEST/" in auth
    url = presigned_get_url(
        "https://bucket.s3.us-east-2.amazonaws.com/key",
        access_key="AKIATEST",
        secret_key="secret",
        region="us-east-2",
    )
    assert "X-Amz-Signature=" in url
    assert "X-Amz-Expires=" in url


def test_content_disposition_encodes_quotes_and_unicode():
    from app.core.privacy import content_disposition

    header = content_disposition("inline", 'nota "Q1".csv')
    assert "\n" not in header
    assert "filename*=UTF-8''" in header
    assert 'filename="nota _Q1_.csv"' in header
    injected = content_disposition("inline", "evil\r\nContent-Type: text/html")
    assert "\r" not in injected and "\n" not in injected
