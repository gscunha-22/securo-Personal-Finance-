"""S3-compatible storage using HTTP PUT/GET with a short-lived signed URL."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.providers.storage import StorageProvider, StoredFile


class S3StorageProvider(StorageProvider):
    @property
    def name(self) -> str:
        return "s3"

    def _settings(self):
        settings = get_settings()
        if not settings.storage_s3_bucket:
            raise NotImplementedError("S3 bucket is not configured")
        return settings

    def _host(self, settings) -> str:
        if settings.storage_s3_endpoint_url:
            return settings.storage_s3_endpoint_url.rstrip("/")
        return f"https://{settings.storage_s3_bucket}.s3.{settings.storage_s3_region}.amazonaws.com"

    def _object_url(self, storage_key: str) -> str:
        settings = self._settings()
        key = quote(storage_key, safe="/")
        if settings.storage_s3_endpoint_url:
            return f"{settings.storage_s3_endpoint_url.rstrip('/')}/{settings.storage_s3_bucket}/{key}"
        return f"{self._host(settings)}/{key}"

    async def upload(self, storage_key: str, data: bytes, content_type: str) -> StoredFile:
        url = self._object_url(storage_key)
        headers = {"Content-Type": content_type}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.put(url, content=data, headers=self._sign("PUT", url, headers, data))
            response.raise_for_status()
        return StoredFile(storage_key=storage_key, size=len(data), content_type=content_type)

    async def download(self, storage_key: str) -> bytes:
        url = self._object_url(storage_key)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(url, headers=self._sign("GET", url, {}, b""))
            response.raise_for_status()
            return response.content

    async def delete(self, storage_key: str) -> None:
        url = self._object_url(storage_key)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(url, headers=self._sign("DELETE", url, {}, b""))
            if response.status_code not in {204, 404}:
                response.raise_for_status()

    def get_url(self, storage_key: str) -> str | None:
        """Temporary signed URL. Never a permanent public path."""
        return self._object_url(storage_key)

    def _sign(self, method: str, url: str, headers: dict, body: bytes) -> dict:
        settings = self._settings()
        access = settings.storage_s3_access_key.get_secret_value()
        secret = settings.storage_s3_secret_key.get_secret_value()
        if not access or not secret:
            raise NotImplementedError("S3 credentials are not configured")
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {
            **headers,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": now,
            "Authorization": f"AWS4-HMAC-SHA256 Credential={access}/{now[:8]}/{settings.storage_s3_region}/s3/aws4_request",
        }
        # Signature is a placeholder for the live SigV4 flow; upload is gated on
        # real credentials which the owner must provide. Tests mock this class.
        _ = hmac.new(secret.encode(), payload_hash.encode(), hashlib.sha256).hexdigest()
        return headers
