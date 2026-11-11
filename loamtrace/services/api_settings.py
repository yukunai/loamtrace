from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib import error, parse, request

import loamtrace.config
from loamtrace.models import ApiSettingsRequest


SETTINGS_PATH = loamtrace.config.WORKSPACE_ROOT / "api_settings.json"
DEFAULT_SETTINGS = {
    "provider": "openai-compatible",
    "base_url": "",
    "model": "",
}


def get_api_settings() -> dict:
    data = _read_settings()
    return _public_settings(data)


def save_api_settings(request: ApiSettingsRequest) -> dict:
    existing = _read_settings()
    next_settings = {
        "provider": request.provider.strip() or DEFAULT_SETTINGS["provider"],
        "base_url": request.base_url.strip(),
        "model": request.model.strip(),
    }
    existing_key = existing.get("api_key")
    if request.clear_api_key:
        existing_key = None
    elif request.api_key is not None:
        stripped_key = request.api_key.strip()
        existing_key = stripped_key or None
    if existing_key:
        next_settings["api_key"] = existing_key
    _write_settings(next_settings)
    return _public_settings(next_settings)


def test_api_connection(request_payload: ApiSettingsRequest) -> dict:
    stored = _read_settings()
    provider = request_payload.provider.strip() or stored.get("provider") or DEFAULT_SETTINGS["provider"]
    base_url = (request_payload.base_url.strip() or stored.get("base_url") or "").rstrip("/")
    model = request_payload.model.strip() or stored.get("model") or ""
    api_key = request_payload.api_key.strip() if request_payload.api_key is not None else stored.get("api_key") or ""

    if request_payload.clear_api_key:
        api_key = ""
    if not base_url:
        return _connection_result(False, provider, base_url, model, "missing_base_url")
    if not api_key:
        return _connection_result(False, provider, base_url, model, "missing_api_key")

    target_url, headers = _connection_probe(provider, base_url, api_key)
    try:
        status, body = _send_test_request(target_url, headers)
    except error.HTTPError as exc:
        return _connection_result(
            False,
            provider,
            base_url,
            model,
            "http_error",
            checked_url=_redact_key_from_url(target_url),
            http_status=exc.code,
            detail=_redact_secret_text(_safe_error_body(exc), api_key),
        )
    except Exception as exc:
        return _connection_result(
            False,
            provider,
            base_url,
            model,
            "network_error",
            checked_url=_redact_key_from_url(target_url),
            detail=_redact_secret_text(str(exc), api_key),
        )

    available_models = _available_model_ids(body)
    model_status = _model_status(available_models, model)
    return _connection_result(
        True,
        provider,
        base_url,
        model,
        "connected",
        checked_url=_redact_key_from_url(target_url),
        http_status=status,
        model_status=model_status,
        available_models=available_models[:20],
    )


def get_configured_api_secret() -> dict:
    """Internal helper for future model-provider wiring; never expose this via API."""
    return _read_settings()


def _read_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)
    if not isinstance(loaded, dict):
        return dict(DEFAULT_SETTINGS)
    settings = dict(DEFAULT_SETTINGS)
    for key in ("provider", "base_url", "model", "api_key"):
        value = loaded.get(key)
        if isinstance(value, str):
            settings[key] = value
    return settings


def _write_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(SETTINGS_PATH, 0o600)
    except OSError:
        pass


def _public_settings(settings: dict[str, Any]) -> dict:
    path = Path(SETTINGS_PATH)
    return {
        "provider": settings.get("provider") or DEFAULT_SETTINGS["provider"],
        "base_url": settings.get("base_url") or "",
        "model": settings.get("model") or "",
        "api_key_configured": bool(settings.get("api_key")),
        "settings_path": str(path),
    }


def _connection_probe(provider: str, base_url: str, api_key: str) -> tuple[str, dict[str, str]]:
    normalized = provider.lower()
    if normalized == "gemini":
        separator = "&" if "?" in base_url else "?"
        return f"{base_url.rstrip('/')}/models{separator}key={parse.quote(api_key)}", {}
    if normalized == "anthropic":
        return (
            f"{base_url.rstrip('/')}/v1/models",
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    return (
        f"{base_url.rstrip('/')}/models",
        {
            "Authorization": f"Bearer {api_key}",
        },
    )


def _send_test_request(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    req = request.Request(
        url,
        headers={
            **headers,
            "Accept": "application/json",
            "User-Agent": "LoamTrace/0.1 API connection test",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=12) as response:
        return response.status, response.read(512_000)


def _available_model_ids(body: bytes) -> list[str]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    seen = set()
    ordered: list[str] = []
    for model_id in _extract_model_ids(payload):
        if model_id in seen:
            continue
        seen.add(model_id)
        ordered.append(model_id)
    return ordered


def _model_status(available_models: list[str], model: str) -> str:
    if not model:
        return "not_checked"
    if not available_models:
        return "unknown"
    return "found" if model in available_models else "not_found"


def _extract_model_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        model_id = value.get("id") or value.get("name")
        if isinstance(model_id, str):
            ids.append(model_id)
        data = value.get("data") or value.get("models")
        if isinstance(data, list):
            for item in data:
                ids.extend(_extract_model_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.extend(_extract_model_ids(item))
    return ids


def _connection_result(
    ok: bool,
    provider: str,
    base_url: str,
    model: str,
    status: str,
    *,
    checked_url: Optional[str] = None,
    http_status: Optional[int] = None,
    model_status: str = "not_checked",
    available_models: Optional[list[str]] = None,
    detail: Optional[str] = None,
) -> dict:
    return {
        "ok": ok,
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "status": status,
        "checked_url": checked_url,
        "http_status": http_status,
        "model_status": model_status,
        "available_models": available_models or [],
        "detail": detail,
    }


def _redact_key_from_url(url: str) -> str:
    parsed = parse.urlsplit(url)
    query = parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [(key, "***" if key.lower() in {"key", "api_key"} else value) for key, value in query]
    return parse.urlunsplit(parsed._replace(query=parse.urlencode(redacted)))


def _redact_secret_text(value: str, api_key: str = "") -> str:
    redacted = _redact_url_secrets(value)
    if api_key:
        redacted = redacted.replace(api_key, "***")
        encoded_key = parse.quote(api_key, safe="")
        redacted = redacted.replace(encoded_key, "***")
        redacted = redacted.replace(parse.quote(api_key), "***")
    return redacted


def _redact_url_secrets(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}=***"

    return re.sub(r"([?&](?:key|api_key|access_token|token|secret))=([^&\s]+)", replace, value, flags=re.IGNORECASE)


def _safe_error_body(exc: error.HTTPError) -> str:
    try:
        return exc.read(4096).decode("utf-8", errors="replace")
    except Exception:
        return str(exc)
