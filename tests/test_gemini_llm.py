from __future__ import annotations

import json

import httpx
import pytest

from mayzcats.config import Settings, required_secrets
from mayzcats.llm import GeminiInteractionsClient, OpenAICompatibleClient, create_llm
from mayzcats.storage import DriveLayout


@pytest.mark.parametrize("shape", ["steps", "outputs"])
def test_gemini_interactions_request_and_json_output(shape):
    def handle(request):
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/interactions"
        assert request.headers["x-goog-api-key"] == "test-key"
        assert request.headers["Api-Revision"] == "2026-05-20"
        assert "authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["model"] == "gemini-3.8-flash"
        assert payload["input"] == "Suggest an unused topic"
        assert payload["system_instruction"].startswith("Planner")
        assert payload["store"] is False
        assert payload["response_format"]["mime_type"] == "application/json"
        content = [{"type": "text", "text": '{"candidates": [{"subject": "kneading"}]}'}]
        data = {"status": "completed"}
        if shape == "steps":
            data["steps"] = [
                {"type": "thought", "content": [{"type": "text", "text": "ignore this"}]},
                {"type": "model_output", "content": content},
            ]
        else:
            data["outputs"] = content
        return httpx.Response(200, json=data)
    client = GeminiInteractionsClient("test-key", http=httpx.Client(transport=httpx.MockTransport(handle)))
    assert client.json("Planner", "Suggest an unused topic") == {
        "candidates": [{"subject": "kneading"}]
    }


@pytest.mark.parametrize("data", [
    {"status": "failed"},
    {"status": "in_progress", "outputs": [{"type": "text", "text": '{"ok":true}'}]},
    {"status": "completed", "outputs": []},
    {"status": "completed", "outputs": [{"type": "text", "text": "[]"}]},
    {"status": "completed", "outputs": [{"type": "text", "text": '{"ok":true} trailing'}]},
])
def test_gemini_rejects_incomplete_or_invalid_json(data):
    client = GeminiInteractionsClient("test-key", http=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    ))
    with pytest.raises(ValueError):
        client.json("system", "user")


def test_gemini_http_rejection_is_not_parsed_as_content():
    client = GeminiInteractionsClient("test-key", http=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "denied"}))
    ))
    with pytest.raises(httpx.HTTPStatusError):
        client.json("system", "user")


def test_selected_provider_controls_environment_secrets_and_factory(tmp_path, monkeypatch):
    from pathlib import Path

    layout = DriveLayout.bootstrap(tmp_path, Path(__file__).resolve().parents[1] / "config")
    layout.pipeline_config.write_text("llm:\n  provider: gemini\n  model: gemini-3.8-flash\n")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    settings = Settings.load(layout)
    assert settings.secrets["GEMINI_API_KEY"] == "test-key"
    assert isinstance(create_llm(settings), GeminiInteractionsClient)
    assert "GEMINI_API_KEY" in required_secrets(settings.pipeline)
    assert not any(name.startswith("OPENAI_") for name in required_secrets(settings.pipeline))
    settings.pipeline["llm"]["provider"] = "openai"
    settings.secrets.update(OPENAI_BASE_URL="https://example.test/v1",
                            OPENAI_API_KEY="test-key")
    # llm.model is the single model knob; it is not duplicated as an OPENAI_MODEL secret.
    settings.pipeline["llm"]["model"] = "openai/gpt-oss-120b"
    assert create_llm(settings).model == "openai/gpt-oss-120b"
    assert isinstance(create_llm(settings), OpenAICompatibleClient)
    assert "GEMINI_API_KEY" not in required_secrets(settings.pipeline)
    settings.pipeline["llm"]["provider"] = "typo"
    with pytest.raises(ValueError, match="Unsupported"):
        create_llm(settings)


def test_llm_rotates_to_the_next_key_on_quota_rejection_and_sticks_to_it() -> None:
    import httpx

    from mayzcats.llm import OpenAICompatibleClient

    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        if request.headers.get("authorization") == "Bearer gsk_1":
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    client = OpenAICompatibleClient(
        "https://x/v1", "gsk_1, gsk_2", "m",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        progress=lambda message: None,
    )
    assert client.api_keys == ["gsk_1", "gsk_2"]
    assert client.json("s", "u") == {"ok": True}
    assert seen == ["Bearer gsk_1", "Bearer gsk_2"]

    # The working key is preferred from now on instead of replaying the exhausted one.
    assert client.json("s", "u") == {"ok": True}
    assert seen[2:] == ["Bearer gsk_2"]
