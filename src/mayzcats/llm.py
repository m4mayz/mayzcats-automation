from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from .network import post_with_retries


def _print_progress(message: str) -> None:
    print(message, flush=True)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object from a model response."""

    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("LLM response did not contain a valid JSON object")


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 180.0,
        max_attempts: int = 3,
        progress: Callable[[str], None] = _print_progress,
        http: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip() or not model.strip():
            raise ValueError("OPENAI_BASE_URL and OPENAI_MODEL are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=min(30.0, timeout)))
        self.max_attempts = max_attempts
        self.progress = progress

    @property
    def chat_endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def json(self, system: str, user: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
        }
        response = post_with_retries(
            self.http,
            self.chat_endpoint,
            label="LLM chat completion",
            max_attempts=self.max_attempts,
            progress=self.progress,
            headers=headers,
            json=payload,
        )
        if response.status_code == 400:
            # Some OpenAI-compatible gateways do not implement response_format.
            payload.pop("response_format")
            response = post_with_retries(
                self.http,
                self.chat_endpoint,
                label="LLM chat completion without response_format",
                max_attempts=self.max_attempts,
                progress=self.progress,
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("OpenAI-compatible endpoint returned an unexpected shape") from exc
        if not isinstance(content, str):
            raise ValueError("Model response content must be text")
        return extract_json_object(content)


class GeminiInteractionsClient:
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(
        self, api_key: str, model: str = "gemini-3.8-flash", *,
        api_revision: str = "2026-05-20", timeout: float = 180.0,
        max_attempts: int = 3, progress: Callable[[str], None] = _print_progress,
        http: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip() or not model.strip():
            raise ValueError("GEMINI_API_KEY and llm.model are required")
        self.api_key, self.model, self.api_revision = api_key, model, api_revision
        self.http = http or httpx.Client(timeout=httpx.Timeout(timeout, connect=min(30.0, timeout)))
        self.max_attempts, self.progress = max_attempts, progress

    def json(self, system: str, user: str) -> dict[str, Any]:
        response = post_with_retries(
            self.http, self.ENDPOINT, label="Gemini interaction",
            max_attempts=self.max_attempts, progress=self.progress,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json",
                     "Api-Revision": self.api_revision},
            json={"model": self.model, "input": user,
                  "system_instruction": system + "\nReturn only a valid JSON object.",
                  "store": False, "generation_config": {"temperature": 0.4},
                  "response_format": {"type": "text", "mime_type": "application/json"}},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "completed":
            raise ValueError("Gemini interaction did not complete")
        # REST revisions expose either model_output steps or an outputs array.
        parts = [part for step in data.get("steps", [])
                 if step.get("type") == "model_output" for part in step.get("content", [])]
        if not parts:
            parts = data.get("outputs", [])
        content = "".join(part["text"] for part in parts
                          if part.get("type") == "text" and isinstance(part.get("text"), str))
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("Gemini response must be a JSON object")
        return value


def create_llm(settings, *, progress: Callable[[str], None] = _print_progress):
    from .config import llm_secrets

    provider = str(settings.value("llm.provider", "openai"))
    settings.require_secrets(*llm_secrets(provider))
    options = {
        "timeout": float(settings.value("network.llm_read_timeout_seconds", 180)),
        "max_attempts": int(settings.value("network.max_attempts", 3)),
        "progress": progress,
    }
    if provider == "gemini":
        return GeminiInteractionsClient(
            settings.secrets["GEMINI_API_KEY"],
            str(settings.value("llm.model", "gemini-3.8-flash")),
            api_revision=str(settings.value("llm.api_revision", "2026-05-20")), **options,
        )
    return OpenAICompatibleClient(
        settings.secrets["OPENAI_BASE_URL"], settings.secrets["OPENAI_API_KEY"],
        settings.secrets["OPENAI_MODEL"], **options,
    )
