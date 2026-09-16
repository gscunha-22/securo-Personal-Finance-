#!/usr/bin/env python3
"""Copy vault objects to/from an S3-compatible bucket using stdlib + SigV4.

Used by backup-instance.sh / restore-instance.sh. Reads STORAGE_S3_* from the
environment. Does not print credentials.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str) -> bytes:
    k_date = _hmac(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def _creds() -> tuple[str, str, str, str, str]:
    bucket = os.environ.get("STORAGE_S3_BUCKET", "").strip()
    access = os.environ.get("STORAGE_S3_ACCESS_KEY", "").strip()
    secret = os.environ.get("STORAGE_S3_SECRET_KEY", "").strip()
    region = os.environ.get("STORAGE_S3_REGION", "").strip() or "us-east-1"
    endpoint = os.environ.get("STORAGE_S3_ENDPOINT_URL", "").strip().rstrip("/")
    if not bucket or not access or not secret:
        raise SystemExit("STORAGE_S3_BUCKET, STORAGE_S3_ACCESS_KEY and STORAGE_S3_SECRET_KEY are required")
    if not endpoint:
        endpoint = f"https://{bucket}.s3.{region}.amazonaws.com"
        return access, secret, region, bucket, endpoint
    return access, secret, region, bucket, endpoint


def _object_url(endpoint: str, bucket: str, key: str, *, path_style: bool) -> str:
    quoted = urllib.parse.quote(key, safe="/")
    if path_style:
        return f"{endpoint}/{bucket}/{quoted}"
    return f"{endpoint}/{quoted}"


def _path_style(endpoint: str, bucket: str) -> bool:
    host = urllib.parse.urlparse(endpoint).netloc
    return not host.startswith(f"{bucket}.")


def sigv4_headers(
    method: str,
    url: str,
    *,
    access: str,
    secret: str,
    region: str,
    body: bytes = b"",
) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    datestamp = now[:8]
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "host": parsed.netloc,
        "x-amz-date": now,
        "x-amz-content-sha256": payload_hash,
    }
    signed = sorted(headers)
    canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in signed)
    signed_headers = ";".join(signed)
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}"
        for k, v in sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
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
        _signing_key(secret, datestamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "x-amz-date": now,
        "x-amz-content-sha256": payload_hash,
        "Host": parsed.netloc,
    }


def _request(method: str, url: str, *, access: str, secret: str, region: str, body: bytes = b"") -> bytes:
    headers = sigv4_headers(method, url, access=access, secret=secret, region=region, body=body)
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"S3 {method} failed: HTTP {exc.code}") from exc


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def list_keys(access: str, secret: str, region: str, bucket: str, endpoint: str) -> list[str]:
    path_style = _path_style(endpoint, bucket)
    keys: list[str] = []
    token: str | None = None
    while True:
        query = {"list-type": "2"}
        if token:
            query["continuation-token"] = token
        qs = urllib.parse.urlencode(sorted(query.items()))
        url = f"{endpoint}/{bucket}?{qs}" if path_style else f"{endpoint}/?{qs}"
        xml = _request("GET", url, access=access, secret=secret, region=region)
        root = ET.fromstring(xml)
        for node in root.iter():
            if _local(node.tag) == "Key" and node.text:
                keys.append(node.text)
        truncated = "false"
        next_token = None
        for node in root.iter():
            name = _local(node.tag)
            if name == "IsTruncated" and node.text:
                truncated = node.text
            if name == "NextContinuationToken" and node.text:
                next_token = node.text
        if truncated.lower() != "true" or not next_token:
            break
        token = next_token
    return keys


def pull(dest: Path) -> int:
    access, secret, region, bucket, endpoint = _creds()
    path_style = _path_style(endpoint, bucket)
    dest.mkdir(parents=True, exist_ok=True)
    keys = list_keys(access, secret, region, bucket, endpoint)
    for key in keys:
        target = dest / key
        if target.is_dir() or key.endswith("/"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        url = _object_url(endpoint, bucket, key, path_style=path_style)
        target.write_bytes(_request("GET", url, access=access, secret=secret, region=region))
    return len(keys)


def push(src: Path) -> int:
    access, secret, region, bucket, endpoint = _creds()
    path_style = _path_style(endpoint, bucket)
    count = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        key = path.relative_to(src).as_posix()
        url = _object_url(endpoint, bucket, key, path_style=path_style)
        body = path.read_bytes()
        _request("PUT", url, access=access, secret=secret, region=region, body=body)
        count += 1
    return count


def main(argv: list[str]) -> None:
    if len(argv) != 3 or argv[1] not in {"pull", "push"}:
        raise SystemExit("Usage: vault_s3.py pull|push <directory>")
    directory = Path(argv[2])
    if argv[1] == "pull":
        n = pull(directory)
        print(f"Vault pull: {n} object(s)")
    else:
        n = push(directory)
        print(f"Vault push: {n} object(s)")


if __name__ == "__main__":
    main(sys.argv)
