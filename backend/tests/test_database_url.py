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


def test_helm_and_compose_expose_neon_s3_without_nextjs():
    values = (REPO_ROOT / "charts" / "securo" / "values.yaml").read_text(encoding="utf-8")
    assert "databaseUrlDirect" in values
    assert "storageProvider" in values
    assert "storageS3AccessKey" in values
    assert "storageS3SecretKey" in values
    assert "privateInstance" in values
    assert "gscunha-22/securo-backend" in values
    assert "securo-finance/securo-backend" not in values
    assert "googleClientId" in values
    assert "microsoftClientSecret" in values
    overlay = (REPO_ROOT / "docker-compose.neon.yml").read_text(encoding="utf-8")
    assert "STORAGE_PROVIDER" in overlay
    assert "DATABASE_URL_DIRECT" in overlay
    assert "local-postgres" in overlay
    assert "--build" in overlay
    backup = (REPO_ROOT / "scripts" / "backup-instance.sh").read_text(encoding="utf-8")
    assert "vault_s3.py" in backup
    assert (REPO_ROOT / "scripts" / "vault_s3.py").is_file()
    prod = (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "context: ./backend" in prod
    assert "securo-finance/securo-backend" not in prod
    assert "start-worker.sh worker" in prod
    assert "start-worker.sh beat" in prod
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "start-worker.sh worker" in compose
    assert "start-worker.sh beat" in compose
    readme = (REPO_ROOT / "charts" / "securo" / "README.md").read_text(encoding="utf-8")
    assert "Deploys the Next.js" not in readme
    assert "Vite" in readme
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "tesseract-ocr-por" in dockerfile
    assert "start-api.sh" in dockerfile
    starter = (REPO_ROOT / "backend" / "scripts" / "start-api.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in starter
    assert "${PORT:-8000}" in starter
    worker_boot = (REPO_ROOT / "backend" / "scripts" / "start-worker.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in worker_boot
    assert "celery -A app.worker" in worker_boot
    render = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "start-worker.sh worker" in render
    assert "start-worker.sh beat" in render
    assert "start-api.sh" in render
    assert "healthCheckPath: /api/ready" in render
    assert "healthCheckPath: /api/health" not in render
    worker_deploy = (REPO_ROOT / "charts" / "securo" / "templates" / "worker" / "deployment.yaml").read_text(
        encoding="utf-8"
    )
    beat_deploy = (REPO_ROOT / "charts" / "securo" / "templates" / "beat" / "deployment.yaml").read_text(
        encoding="utf-8"
    )
    assert "start-worker.sh" in worker_deploy
    assert "start-worker.sh" in beat_deploy
    backend_deploy = (REPO_ROOT / "charts" / "securo" / "templates" / "backend" / "deployment.yaml").read_text(
        encoding="utf-8"
    )
    assert "start-api.sh" in backend_deploy
    assert "path: /api/ready" in backend_deploy
    assert "autoDeploy: false" in render
    assert "type: redis" in render
    assert "nextjs" not in render.lower()
    assert "type: cron" not in render
    assert "DATABASE_URL_DIRECT" in render
    assert "TRUSTED_PROXY_HOPS" in render
    assert render.count("STORAGE_S3_BUCKET") >= 3
    assert render.count("GOOGLE_CLIENT_ID") >= 3
    assert render.count("FRONTEND_URL") >= 3
    intelligence_tasks = (REPO_ROOT / "backend" / "app" / "tasks" / "intelligence_tasks.py").read_text(
        encoding="utf-8"
    )
    assert "make_worker_session_maker" in intelligence_tasks
    assert "async_session_maker" not in intelligence_tasks
    assert "list_ready_queued" in intelligence_tasks
    assert "sync_connected_sources" in intelligence_tasks
    assert "process_sync" in intelligence_tasks
    dispatch = (REPO_ROOT / "backend" / "app" / "services" / "job_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert "PYTEST_CURRENT_TEST" in dispatch
    assert "process_document" in dispatch
    assert "process_sync" in dispatch
    vault = (REPO_ROOT / "backend" / "app" / "services" / "vault_service.py").read_text(encoding="utf-8")
    assert "job_dispatch" in vault
    worker = (REPO_ROOT / "backend" / "app" / "worker.py").read_text(encoding="utf-8")
    assert (
        '"task": "app.tasks.intelligence_tasks.recover_abandoned_jobs",\n        "schedule": 60,'
        in worker
    )
    assert "app.tasks.intelligence_tasks.sync_connected_sources" in worker


def test_vercel_spa_rewrites_api_to_persistent_origin():
    for relative in ("frontend/vercel.ts", "vercel.ts"):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "API_ORIGIN" in source
        assert "/api/:path*" in source
        assert "connect-src 'self'" in source
        assert "index.html" in source
        assert 'framework: "vite"' in source
        assert "deploymentEnabled: false" in source
        assert "@vercel/config/v1" in source
        assert "ignoreCommand" not in source
        assert "nextjs" not in source.lower()
        assert "throw new Error" not in source
    root = (REPO_ROOT / "vercel.ts").read_text(encoding="utf-8")
    assert "npm run build --prefix frontend" in root
    assert "frontend/dist" in root
    assert not (REPO_ROOT / "frontend" / "vercel.json").exists()
    assert not (REPO_ROOT / "vercel.json").exists()
    txn = (REPO_ROOT / "backend" / "app" / "services" / "transaction_service.py").read_text(
        encoding="utf-8"
    )
    assert "async def _get_workspace_account" in txn
    assert "account_in_workspace" in txn
    filters = (REPO_ROOT / "backend" / "app" / "services" / "_query_filters.py").read_text(
        encoding="utf-8"
    )
    assert "exists().where(" in filters
    assert "BankConnection.id == Account.connection_id" in filters


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
    s3_source = (REPO_ROOT / "backend" / "app" / "providers" / "s3_storage.py").read_text(
        encoding="utf-8"
    )
    assert "list-type=2" in s3_source
    assert "async def ping" in s3_source


def test_content_disposition_encodes_quotes_and_unicode():
    from app.core.privacy import content_disposition

    header = content_disposition("inline", 'nota "Q1".csv')
    assert "\n" not in header
    assert "filename*=UTF-8''" in header
    assert 'filename="nota _Q1_.csv"' in header
    injected = content_disposition("inline", "evil\r\nContent-Type: text/html")
    assert "\r" not in injected and "\n" not in injected
