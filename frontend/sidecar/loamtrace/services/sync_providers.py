from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib import error, parse, request
from xml.etree import ElementTree

from loamtrace.services.paths import safe_project_id
from loamtrace.services.sync_settings import get_configured_sync_secret


class SyncProvider(ABC):
    @abstractmethod
    def put_snapshot(self, project_id: str, snapshot_id: str, archive: Path, metadata: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def list_snapshots(self, project_id: Optional[str] = None) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def get_snapshot_archive(self, snapshot_id: str) -> Path:
        raise NotImplementedError

    @abstractmethod
    def delete_snapshot(self, snapshot_id: str) -> dict:
        raise NotImplementedError


class LocalSyncProvider(SyncProvider):
    def __init__(self, target_dir: str, prefix: str = "loamtrace-sync"):
        if not target_dir or not target_dir.strip():
            raise ValueError("sync_target_dir_required")
        self.target_dir = Path(target_dir).expanduser()
        self.prefix = prefix.strip().strip("/") or "loamtrace-sync"

    def put_snapshot(self, project_id: str, snapshot_id: str, archive: Path, metadata: dict) -> dict:
        from loamtrace.services.sync import _read_sync_metadata, _sha256_file, _sync_root

        target_root = _sync_root(str(self.target_dir))
        project_dir = target_root / "snapshots" / safe_project_id(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        archive_path = project_dir / f"{snapshot_id}.zip"
        metadata_path = project_dir / f"{snapshot_id}.json"
        archive_path.write_bytes(archive.read_bytes())
        local_metadata = {
            **metadata,
            "archive_path": str(archive_path),
            "metadata_path": str(metadata_path),
            "size_bytes": archive_path.stat().st_size,
            "archive_sha256": metadata.get("archive_sha256") or _sha256_file(archive_path),
        }
        metadata_path.write_text(json.dumps(local_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return _read_sync_metadata(metadata_path)

    def list_snapshots(self, project_id: Optional[str] = None) -> list[dict]:
        from loamtrace.services.sync import list_synced_snapshots

        return list_synced_snapshots(str(self.target_dir), project_id)

    def get_snapshot_archive(self, snapshot_id: str) -> Path:
        matches = [item for item in self.list_snapshots() if item["snapshot_id"] == snapshot_id]
        if not matches:
            raise FileNotFoundError("synced_snapshot_not_found")
        archive_path = Path(matches[0]["archive_path"])
        if not archive_path.exists():
            raise FileNotFoundError("synced_snapshot_archive_not_found")
        return archive_path

    def delete_snapshot(self, snapshot_id: str) -> dict:
        matches = [item for item in self.list_snapshots() if item["snapshot_id"] == snapshot_id]
        if not matches:
            raise FileNotFoundError("synced_snapshot_not_found")
        snapshot = matches[0]
        deleted_paths = []
        for key in ("archive_path", "metadata_path"):
            path = Path(snapshot[key])
            if path.exists():
                path.unlink()
                deleted_paths.append(str(path))
        return {**snapshot, "deleted": True, "deleted_paths": deleted_paths}


class S3CompatibleSyncProvider(SyncProvider):
    def __init__(self, settings: dict):
        self.endpoint_url = str(settings.get("endpoint_url") or "").rstrip("/")
        self.bucket = str(settings.get("bucket") or "").strip()
        self.region = str(settings.get("region") or "auto").strip() or "auto"
        self.prefix = str(settings.get("prefix") or "loamtrace-sync").strip().strip("/") or "loamtrace-sync"
        self.access_key_id = str(settings.get("access_key_id") or "")
        self.secret_access_key = str(settings.get("secret_access_key") or "")
        missing = [
            key
            for key in ("endpoint_url", "bucket", "access_key_id", "secret_access_key")
            if not getattr(self, key)
        ]
        if missing:
            raise ValueError("sync_provider_missing_required:" + ",".join(missing))

    def put_snapshot(self, project_id: str, snapshot_id: str, archive: Path, metadata: dict) -> dict:
        zip_key = self._object_key(project_id, snapshot_id, "zip")
        json_key = self._object_key(project_id, snapshot_id, "json")
        self._request("PUT", zip_key, archive.read_bytes(), content_type="application/zip")
        remote_metadata = {
            **metadata,
            "archive_path": f"s3://{self.bucket}/{zip_key}",
            "metadata_path": f"s3://{self.bucket}/{json_key}",
            "object_key": zip_key,
            "metadata_key": json_key,
        }
        self._request(
            "PUT",
            json_key,
            json.dumps(remote_metadata, ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
        )
        return remote_metadata

    def list_snapshots(self, project_id: Optional[str] = None) -> list[dict]:
        prefix = f"{self.prefix}/snapshots/{safe_project_id(project_id)}/" if project_id else f"{self.prefix}/snapshots/"
        body = self._request("GET", "", query={"list-type": "2", "prefix": prefix})
        snapshots = []
        for key in _parse_s3_list_keys(body):
            if not key.endswith(".json"):
                continue
            metadata_body = self._request("GET", key)
            metadata = json.loads(metadata_body.decode("utf-8"))
            archive_key = metadata.get("object_key") or key[:-5] + ".zip"
            snapshots.append(
                {
                    "snapshot_id": metadata.get("snapshot_id") or Path(key).stem,
                    "project_id": metadata.get("project_id") or _project_id_from_key(key),
                    "source_project_id": metadata.get("source_project_id") or metadata.get("project_id"),
                    "created_at": metadata.get("created_at"),
                    "format": metadata.get("format"),
                    "archive_path": metadata.get("archive_path") or f"s3://{self.bucket}/{archive_key}",
                    "metadata_path": metadata.get("metadata_path") or f"s3://{self.bucket}/{key}",
                    "object_key": archive_key,
                    "metadata_key": key,
                    "size_bytes": metadata.get("size_bytes"),
                    "archive_sha256": metadata.get("archive_sha256"),
                    "integrity_status": "unchecked" if metadata.get("archive_sha256") else "unknown",
                    "available": True,
                    "manifest": metadata.get("manifest") or {},
                }
            )
        snapshots.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return snapshots

    def get_snapshot_archive(self, snapshot_id: str) -> Path:
        matches = [item for item in self.list_snapshots() if item["snapshot_id"] == snapshot_id]
        if not matches:
            raise FileNotFoundError("synced_snapshot_not_found")
        body = self._request("GET", str(matches[0]["object_key"]))
        handle = tempfile.NamedTemporaryFile(prefix=f"{snapshot_id}_", suffix=".zip", delete=False)
        with handle:
            handle.write(body)
        return Path(handle.name)

    def delete_snapshot(self, snapshot_id: str) -> dict:
        matches = [item for item in self.list_snapshots() if item["snapshot_id"] == snapshot_id]
        if not matches:
            raise FileNotFoundError("synced_snapshot_not_found")
        snapshot = matches[0]
        deleted_keys = []
        for key in (snapshot.get("object_key"), snapshot.get("metadata_key")):
            if key:
                self._request("DELETE", str(key))
                deleted_keys.append(str(key))
        return {**snapshot, "deleted": True, "deleted_keys": deleted_keys}

    def _object_key(self, project_id: str, snapshot_id: str, suffix: str) -> str:
        return f"{self.prefix}/snapshots/{safe_project_id(project_id)}/{snapshot_id}.{suffix}"

    def _request(
        self,
        method: str,
        key: str,
        body: bytes = b"",
        *,
        query: Optional[dict[str, str]] = None,
        content_type: str = "application/octet-stream",
    ) -> bytes:
        url, path, query_string = self._url(key, query)
        headers = self._signed_headers(method, path, query_string, body, content_type)
        req = request.Request(url, data=body if method in {"PUT", "POST"} else None, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as response:
                return response.read()
        except error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise ValueError(f"s3_provider_http_error:{exc.code}:{detail}") from exc

    def _url(self, key: str, query: Optional[dict[str, str]]) -> tuple[str, str, str]:
        encoded_bucket = parse.quote(self.bucket.strip("/"), safe="")
        encoded_key = "/".join(parse.quote(part, safe="") for part in key.split("/") if part)
        path = f"/{encoded_bucket}" + (f"/{encoded_key}" if encoded_key else "")
        query_string = parse.urlencode(query or {})
        url = f"{self.endpoint_url}{path}" + (f"?{query_string}" if query_string else "")
        return url, path, query_string

    def _signed_headers(self, method: str, path: str, query: str, body: bytes, content_type: str) -> dict[str, str]:
        parsed = parse.urlsplit(self.endpoint_url)
        host = parsed.netloc
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        headers = {
            "host": host,
            "content-type": content_type,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{key}:{headers[key]}\n" for key in sorted(headers))
        canonical_request = "\n".join(
            [method, path or "/", query, canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _sigv4_key(self.secret_access_key, date_stamp, self.region)
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        auth = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {**headers, "Authorization": auth}


def configured_sync_provider() -> SyncProvider:
    settings = get_configured_sync_secret()
    provider = settings.get("provider") or "local"
    if provider == "local":
        return LocalSyncProvider(str(settings.get("target_dir") or ""), str(settings.get("prefix") or "loamtrace-sync"))
    if provider == "s3-compatible":
        return S3CompatibleSyncProvider(settings)
    raise ValueError("unsupported_sync_provider")


def _sigv4_key(secret: str, date_stamp: str, region: str) -> bytes:
    key = ("AWS4" + secret).encode("utf-8")
    for value in (date_stamp, region, "s3", "aws4_request"):
        key = hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
    return key


def _parse_s3_list_keys(body: bytes) -> list[str]:
    root = ElementTree.fromstring(body)
    keys = []
    for element in root.iter():
        if element.tag.endswith("Key") and element.text:
            keys.append(element.text)
    return keys


def _project_id_from_key(key: str) -> str:
    parts = key.split("/")
    try:
        return parts[parts.index("snapshots") + 1]
    except (ValueError, IndexError):
        return ""
