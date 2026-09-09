from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values

from .storage import DriveLayout

REQUIRED_SECRETS = (
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "ELEVENLABS_API_KEYS",
    "PEXELS_API_KEY",
    "PIXABAY_API_KEY",
    "TAVILY_API_KEY",
)


def llm_secrets(provider: str) -> tuple[str, ...]:
    if provider == "gemini":
        return ("GEMINI_API_KEY",)
    if provider == "openai":
        return ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")
    raise ValueError(f"Unsupported llm.provider: {provider}")


def required_secrets(pipeline: dict[str, Any]) -> tuple[str, ...]:
    return llm_secrets(str(pipeline.get("llm", {}).get("provider", "openai"))) + REQUIRED_SECRETS[3:]


@dataclass(slots=True)
class Settings:
    layout: DriveLayout
    channel: dict[str, Any]
    pipeline: dict[str, Any]
    secrets: dict[str, str]
    work_root: Path
    mpt_root: Path

    @classmethod
    def load(
        cls,
        layout: DriveLayout,
        *,
        work_root: Path = Path("/content/mayzcats/runs"),
        mpt_root: Path = Path("/content/mayzcats-project/vendor/MoneyPrinterTurbo"),
    ) -> Settings:
        channel = _read_yaml(layout.channel_config)
        pipeline = _read_yaml(layout.pipeline_config)
        file_values = {key: value or "" for key, value in dotenv_values(layout.env_file).items()}
        secrets = {
            key: os.environ.get(key, file_values.get(key, ""))
            for key in set(file_values) | set(REQUIRED_SECRETS) | {"GEMINI_API_KEY"}
        }
        return cls(layout, channel, pipeline, secrets, Path(work_root), Path(mpt_root))

    def value(self, dotted_path: str, default: Any = None) -> Any:
        current: Any = self.pipeline
        for part in dotted_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def require_secrets(self, *names: str) -> None:
        missing = [name for name in names if not self.secrets.get(name, "").strip()]
        if missing:
            raise ValueError("Missing required secrets: " + ", ".join(missing))

    def elevenlabs_keys(self) -> list[str]:
        return [
            item.strip()
            for item in self.secrets.get("ELEVENLABS_API_KEYS", "").split(",")
            if item.strip()
        ]

    def __repr__(self) -> str:
        return (
            f"Settings(layout={self.layout!r}, channel={self.channel!r}, "
            f"pipeline={self.pipeline!r}, secrets=<redacted>, work_root={self.work_root!r}, "
            f"mpt_root={self.mpt_root!r})"
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a mapping: {path}")
    return value
