from loamtrace.services import model_provider


def test_post_json_redacts_query_api_key_in_network_errors(monkeypatch):
    def fake_urlopen(_req, timeout):
        raise OSError(
            "failed https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=secret%2Fkey"
        )

    monkeypatch.setattr(model_provider.request, "urlopen", fake_urlopen)

    try:
        model_provider._post_json(
            "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=secret%2Fkey",
            {"ok": True},
            {},
        )
    except model_provider.ModelProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ModelProviderError")

    assert "key=***" in message
    assert "secret" not in message


def test_chat_json_openai_compatible(monkeypatch):
    monkeypatch.setattr(
        model_provider,
        "get_configured_api_secret",
        lambda: {
            "provider": "openai-compatible",
            "base_url": "https://api.example.test/v1",
            "model": "example-model",
            "api_key": "secret",
        },
    )
    calls = []

    def fake_post(url, payload, headers):
        calls.append((url, payload, headers))
        return {"choices": [{"message": {"content": '{"claims":[]}'}}]}

    monkeypatch.setattr(model_provider, "_post_json", fake_post)

    result = model_provider.chat_json("system", "user")

    assert result == {"claims": []}
    url, payload, headers = calls[0]
    assert url == "https://api.example.test/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret"
    assert payload["model"] == "example-model"
    assert payload["messages"][0] == {"role": "system", "content": "system"}
    assert payload["messages"][1] == {"role": "user", "content": "user"}
    assert payload["response_format"] == {"type": "json_object"}


def test_chat_json_anthropic_messages(monkeypatch):
    monkeypatch.setattr(
        model_provider,
        "get_configured_api_secret",
        lambda: {
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-4-20250514",
            "api_key": "secret",
        },
    )
    calls = []

    def fake_post(url, payload, headers):
        calls.append((url, payload, headers))
        return {
            "content": [
                {
                    "type": "text",
                    "text": '```json\n{"claims":[{"text":"ok"}]}\n```',
                }
            ]
        }

    monkeypatch.setattr(model_provider, "_post_json", fake_post)

    result = model_provider.chat_json("system prompt", "user prompt")

    assert result == {"claims": [{"text": "ok"}]}
    url, payload, headers = calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "secret"
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "claude-sonnet-4-20250514"
    assert payload["system"] == "system prompt"
    assert payload["messages"] == [{"role": "user", "content": "user prompt"}]
    assert payload["max_tokens"] == 1200


def test_chat_json_gemini_generate_content(monkeypatch):
    monkeypatch.setattr(
        model_provider,
        "get_configured_api_secret",
        lambda: {
            "provider": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "model": "gemini-2.5-pro",
            "api_key": "secret/key",
        },
    )
    calls = []

    def fake_post(url, payload, headers):
        calls.append((url, payload, headers))
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": '{"claims":[{"text":"ok"}]}'},
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr(model_provider, "_post_json", fake_post)

    result = model_provider.chat_json("system prompt", "user prompt")

    assert result == {"claims": [{"text": "ok"}]}
    url, payload, headers = calls[0]
    assert url == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-2.5-pro:generateContent?key=secret%2Fkey"
    )
    assert headers == {}
    text = payload["contents"][0]["parts"][0]["text"]
    assert "system prompt" in text
    assert "user prompt" in text
    assert payload["generationConfig"]["responseMimeType"] == "application/json"


def test_chat_json_returns_none_when_not_configured(monkeypatch):
    monkeypatch.setattr(
        model_provider,
        "get_configured_api_secret",
        lambda: {"provider": "gemini", "base_url": "", "model": "", "api_key": ""},
    )

    assert model_provider.chat_json("system", "user") is None
