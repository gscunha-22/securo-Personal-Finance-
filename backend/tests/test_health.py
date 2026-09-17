from unittest.mock import patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_ready_check_ok(client: AsyncClient):
    response = await client.get("/api/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "redis": True, "storage": True}


@pytest.mark.asyncio
async def test_ready_check_degraded_returns_503(client: AsyncClient):
    async def boom():
        raise ConnectionError("redis down")

    with patch("app.core.redis.get_redis", boom):
        response = await client.get("/api/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] is True
    assert body["checks"]["redis"] is False
    assert body["checks"]["storage"] is True


@pytest.mark.asyncio
async def test_ready_check_storage_ping_failure_returns_503(client: AsyncClient):
    class BoomStorage:
        async def ping(self):
            raise ConnectionError("s3 down")

    with patch("app.providers.get_storage_provider", return_value=BoomStorage()):
        response = await client.get("/api/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["storage"] is False
    assert body["checks"]["database"] is True
    assert body["checks"]["redis"] is True
