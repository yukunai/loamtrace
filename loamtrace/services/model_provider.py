from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib import error, parse, request

from loamtrace.services.api_settings import get_configured_api_secret


class ModelProviderError(RuntimeError):
    pass


PROVIDER_TIMEOUT_SECONDS = 120


def chat_json(system_prompt: str, user_prompt: str) -> Optional[dict[str, Any]]:
    settings = get_configured_api_secret()
    provider = (settings.get("provider") or "").strip().lower()
    base_url = (settings.get("base_url") or "").strip().rstrip("/")
    model = (settings.get("model") or "").strip()
    api_key = (settings.get("api_key") or "").strip()

    if not base_url or not model or not api_key:
        return None

    if provider == "anthropic":
        return _chat_anthropic(base_url, model, api_key, system_prompt, user_prompt)
    if provider == "gemini":
        return _chat_gemini(base_url, model, api_key, system_prompt, user_prompt)
    return _chat_openai_compatible(base_url, model, api_key, system_prompt, user_prompt)


def _chat_openai_compatible(
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    endpoint = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    response = _post_json(endpoint, payload, {"Authorization": f"Bearer {api_key}"})
    content = _extract_chat_content(response)
    return _parse_model_json(content)


def _chat_anthropic(
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    endpoint = f"{base_url}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 1200,
        "temperature": 0.1,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    response = _post_json(
        endpoint,
        payload,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    content = _extract_anthropic_content(response)
    return _parse_model_json(content)


def _chat_gemini(
    base_url: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    model_path = model if model.startswith("models/") else f"models/{model}"
    endpoint = (
        f"{base_url}/{parse.quote(model_path, safe='/')}:generateContent"
        f"?key={parse.quote(api_key, safe='')}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    response = _post_json(endpoint, payload, {})
    content = _extract_gemini_content(response)
    return _parse_model_json(content)


def _parse_model_json(content: str) -> dict[str, Any]:
    if not content:
        raise ModelProviderError("empty_model_response")
    try:
        parsed = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise ModelProviderError(f"invalid_model_json:{exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelProviderError("model_json_not_object")
    return parsed


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **headers,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "LoamTrace/0.2 model provider",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=PROVIDER_TIMEOUT_SECONDS) as response:
            body = response.read(1_000_000)
    except error.HTTPError as exc:
        detail = _redact_url_secrets(exc.read(4096).decode("utf-8", errors="replace"))
        raise ModelProviderError(f"http_error:{exc.code}:{detail}") from exc
    except Exception as exc:
        raise ModelProviderError(f"network_error:{_redact_url_secrets(str(exc))}") from exc
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelProviderError(f"invalid_provider_json:{exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelProviderError("provider_json_not_object")
    return parsed


def _extract_chat_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _extract_anthropic_content(response: dict[str, Any]) -> str:
    content = response.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _extract_gemini_content(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    texts: list[str] = []
    for item in parts:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            texts.append(text)
    return "\n".join(texts)


def _strip_json_fence(value: str) -> str:
    stripped = value.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _redact_url_secrets(value: str) -> str:
    return re.sub(r"([?&](?:key|api_key)=)[^&\s]+", r"\1***", value, flags=re.IGNORECASE)
