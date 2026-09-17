"""S3-compatible storage using HTTP PUT/GET with SigV4."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

import httpx

from app.core.config import get_settings
from app.providers.storage import StorageProvider, StoredFile


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _hmac(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def sigv4_headers(
    method: str,
    url: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    extra_headers: dict[str, str] | None = None,
    body: bytes = b"",
    amz_date: str | None = None,
) -> dict[str, str]:
    """Complete AWS SigV4 header set (Credential, SignedHeaders, Signature)."""
    parsed = urlparse(url)
    now = amz_date or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    datestamp = now[:8]
    region = region or "us-east-1"
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {k.lower(): v.strip() for k, v in (extra_headers or {}).items()}
    headers["host"] = parsed.netloc
    headers["x-amz-date"] = now
    headers["x-amz-content-sha256"] = payload_hash
    signed = sorted(headers)
    canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in signed)
    signed_headers = ";".join(signed)
    canonical_query = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
        for k, v in sorted(
            (part.split("=", 1) + [""])[:2]
            for part in parsed.query.split("&")
            if part
        )
    )
    canonical = (
        f"{method}\n{parsed.path or '/'}\n{canonical_query}\n"
        f"{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )
    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{now}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, "s3"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signed_out = {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "x-amz-date": now,
        "x-amz-content-sha256": payload_hash,
        "Host": parsed.netloc,
    }
    for key, value in (extra_headers or {}).items():
        signed_out.setdefault(key, value)
    return signed_out


def presigned_get_url(
    url: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    expires: int = 300,
) -> str:
    parsed = urlparse(url)
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = amz_date[:8]
    region = region or "us-east-1"
    scope = f"{datestamp}/{region}/s3/aws4_request"
    credential = f"{access_key}/{scope}"
    signed_headers = "host"
    query_items = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": credential,
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": signed_headers,
    }
    canonical_query = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query_items.items())
    )
    canonical = (
        f"GET\n{parsed.path or '/'}\n{canonical_query}\n"
        f"host:{parsed.netloc}\n\n{signed_headers}\nUNSIGNED-PAYLOAD"
    )
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    )
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, "s3"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{url}?{canonical_query}&X-Amz-Signature={signature}"


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

    def _credentials(self) -> tuple[str, str, str]:
        settings = self._settings()
        access = settings.storage_s3_access_key.get_secret_value()
        secret = settings.storage_s3_secret_key.get_secret_value()
        if not access or not secret:
            raise NotImplementedError("S3 credentials are not configured")
        return access, secret, settings.storage_s3_region or "us-east-1"

    def _sign(self, method: str, url: str, headers: dict, body: bytes) -> dict:
        access, secret, region = self._credentials()
        return sigv4_headers(
            method,
            url,
            access_key=access,
            secret_key=secret,
            region=region,
            extra_headers=headers,
            body=body,
        )

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
        """Temporary signed GET URL. Never a permanent public path."""
        access, secret, region = self._credentials()
        return presigned_get_url(
            self._object_url(storage_key),
            access_key=access,
            secret_key=secret,
            region=region,
            expires=int(timedelta(minutes=5).total_seconds()),
        )
