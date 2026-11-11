from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import loamtrace.config
from cryptography.fernet import Fernet, InvalidToken

from loamtrace.models import SyncSettingsRequest

SETTINGS_PATH = loamtrace.config.WORKSPACE_ROOT / "sync_settings.json"
KEY_PATH = loamtrace.config.WORKSPACE_ROOT / "sync_settings.key"

DEFAULT_SETTINGS = {
    "provider": "local",
    "target_dir": "",
    "endpoint_url": "",
    "bucket": "",
    "region": "",
    "prefix": "loamtrace-sync",
}

SECRET_FIELDS = ("access_key_id", "secret_access_key")


def get_sync_settings() -> dict:
    return _public_settings(_read_settings(decrypt=False))


def save_sync_settings(request: SyncSettingsRequest) -> dict:
    existing_plain = _read_settings(decrypt=True)
    next_settings: dict[str, Any] = {
        "provider": request.provider.strip() or DEFAULT_SETTINGS["provider"],
        "target_dir": request.target_dir.strip(),
        "endpoint_url": request.endpoint_url.strip(),
        "bucket": request.bucket.strip(),
        "region": request.region.strip(),
        "prefix": request.prefix.strip() or DEFAULT_SETTINGS["prefix"],
    }

    for field in SECRET_FIELDS:
        existing_secret = existing_plain.get(field)
        if request.clear_secret:
            existing_secret = None
        else:
            value = getattr(request, field)
            if value is not None:
                stripped = value.strip()
                existing_secret = stripped or None
        if existing_secret:
            next_settings[field] = existing_secret

    _write_settings(next_settings)
    return _public_settings(_read_settings(decrypt=False))


def test_sync_settings(request_payload: SyncSettingsRequest) -> dict:
    settings = _merged_plain_settings(request_payload)
    provider = settings["provider"]
    if provider == "local":
        target_dir = settings.get("target_dir") or ""
        if not target_dir:
            return _test_result(False, provider, "missing_target_dir")
        path = Path(target_dir).expanduser()
        if path.exists() and not path.is_dir():
            return _test_result(False, provider, "target_not_directory", target_dir=str(path))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _test_result(False, provider, "target_unwritable", target_dir=str(path), detail=str(exc))
        return _test_result(True, provider, "ready", target_dir=str(path))

    if provider == "s3-compatible":
        missing = [
            field
            for field in ("endpoint_url", "bucket", "access_key_id", "secret_access_key")
            if not settings.get(field)
        ]
        if missing:
            return _test_result(False, provider, "missing_required_fields", missing_fields=missing)
        return _test_result(
            True,
            provider,
            "configuration_valid",
            detail="S3/R2 credentials are encrypted locally; object upload provider is available through provider sync endpoints.",
        )

    return _test_result(False, provider, "unsupported_provider")


def test_configured_sync_provider_live(project_id: Optional[str] = None) -> dict:
    settings = get_configured_sync_secret()
    provider = settings.get("provider") or "local"
    if provider == "local":
        return test_sync_settings(
            SyncSettingsRequest(
                provider="local",
                target_dir=str(settings.get("target_dir") or ""),
                prefix=str(settings.get("prefix") or DEFAULT_SETTINGS["prefix"]),
            )
        )
    if provider != "s3-compatible":
        return _test_result(False, provider, "unsupported_provider")

    missing = [
        field
        for field in ("endpoint_url", "bucket", "access_key_id", "secret_access_key")
        if not settings.get(field)
    ]
    if missing:
        return _test_result(False, provider, "missing_required_fields", missing_fields=missing)

    try:
        from loamtrace.services.sync_providers import configured_sync_provider

        snapshots = configured_sync_provider().list_snapshots(project_id)
    except Exception as exc:
        return _test_result(
            False,
            provider,
            "live_check_failed",
            detail=_redact_sync_error(str(exc), settings),
        )
    return _test_result(
        True,
        provider,
        "live_ready",
        detail=f"Provider list check succeeded with {len(snapshots)} snapshot(s).",
    )


def get_configured_sync_secret() -> dict:
    """Internal helper for sync providers; never return this from public API."""
    return _read_settings(decrypt=True)


def _merged_plain_settings(request_payload: SyncSettingsRequest) -> dict[str, Any]:
    stored = _read_settings(decrypt=True)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    for field in ("provider", "target_dir", "endpoint_url", "bucket", "region", "prefix"):
        value = getattr(request_payload, field)
        if isinstance(value, str) and value.strip():
            merged[field] = value.strip()
    if request_payload.clear_secret:
        for field in SECRET_FIELDS:
            merged.pop(field, None)
    else:
        for field in SECRET_FIELDS:
            value = getattr(request_payload, field)
            if value is not None:
                stripped = value.strip()
                if stripped:
                    merged[field] = stripped
    return merged


def _read_settings(decrypt: bool) -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)
    if not isinstance(loaded, dict):
        return dict(DEFAULT_SETTINGS)

    settings = dict(DEFAULT_SETTINGS)
    for key in ("provider", "target_dir", "endpoint_url", "bucket", "region", "prefix"):
        value = loaded.get(key)
        if isinstance(value, str):
            settings[key] = value
    encrypted = loaded.get("secrets")
    if isinstance(encrypted, dict):
        for field in SECRET_FIELDS:
            token = encrypted.get(field)
            if isinstance(token, str):
                if decrypt:
                    settings[field] = _decrypt_secret(token)
                else:
                    settings[field] = "__configured__"
    return settings


def _write_settings(settings: dict[str, Any]) -> None:
    public = {
        key: settings.get(key) or DEFAULT_SETTINGS[key]
        for key in ("provider", "target_dir", "endpoint_url", "bucket", "region", "prefix")
    }
    secrets = {}
    for field in SECRET_FIELDS:
        value = settings.get(field)
        if isinstance(value, str) and value:
            secrets[field] = _encrypt_secret(value)
    if secrets:
        public["secrets"] = secrets
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    _chmod_private(SETTINGS_PATH)


def _public_settings(settings: dict[str, Any]) -> dict:
    return {
        "provider": settings.get("provider") or DEFAULT_SETTINGS["provider"],
        "target_dir": settings.get("target_dir") or "",
        "endpoint_url": settings.get("endpoint_url") or "",
        "bucket": settings.get("bucket") or "",
        "region": settings.get("region") or "",
        "prefix": settings.get("prefix") or DEFAULT_SETTINGS["prefix"],
        "access_key_configured": bool(settings.get("access_key_id")),
        "secret_key_configured": bool(settings.get("secret_access_key")),
        "settings_path": str(SETTINGS_PATH),
    }


def _fernet() -> Fernet:
    key = _read_or_create_key()
    return Fernet(key)


def _read_or_create_key() -> bytes:
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    _chmod_private(KEY_PATH)
    return key


def _encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("sync_secret_decryption_failed") from exc


def _redact_sync_error(message: str, settings: dict[str, Any]) -> str:
    redacted = message
    for field in SECRET_FIELDS:
        value = settings.get(field)
        if isinstance(value, str) and value:
            redacted = redacted.replace(value, "[redacted]")
    return redacted[:1000]


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _test_result(
    ok: bool,
    provider: str,
    status: str,
    *,
    target_dir: Optional[str] = None,
    missing_fields: Optional[list[str]] = None,
    detail: Optional[str] = None,
) -> dict:
    return {
        "ok": ok,
        "provider": provider,
        "status": status,
        "target_dir": target_dir,
        "missing_fields": missing_fields or [],
        "detail": detail,
    }
