from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DriveLayout:
    root: Path
    config_dir: Path
    secrets_dir: Path
    youtube_secrets_dir: Path
    state_dir: Path
    failed_dir: Path
    logs_dir: Path
    runs_dir: Path
    tts_cache_dir: Path
    channel_config: Path
    pipeline_config: Path
    env_file: Path
    client_secret: Path
    token_file: Path
    topic_history: Path
    runs_log: Path

    @classmethod
    def bootstrap(cls, root: Path, defaults_dir: Path) -> DriveLayout:
        root = Path(root)
        config_dir = root / "config"
        secrets_dir = root / "secrets"
        youtube_secrets_dir = secrets_dir / "youtube"
        state_dir = root / "state"
        failed_dir = root / "failed"
        logs_dir = root / "logs"
        runs_dir = root / "runs"
        tts_cache_dir = root / "cache" / "tts"
        for directory in (
            config_dir,
            youtube_secrets_dir,
            state_dir,
            failed_dir,
            logs_dir,
            runs_dir,
            tts_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        channel_config = config_dir / "channel.yaml"
        pipeline_config = config_dir / "pipeline.yaml"
        env_file = secrets_dir / ".env"
        cls._copy_default(defaults_dir / "channel.example.yaml", channel_config)
        cls._copy_default(defaults_dir / "pipeline.example.yaml", pipeline_config)
        env_example = defaults_dir / ".env.example"
        if not env_example.exists():
            env_example = defaults_dir.parent / ".env.example"
        cls._copy_default(env_example, env_file)

        topic_history = state_dir / "topic_history.json"
        if not topic_history.exists():
            cls.atomic_json(topic_history, [])
        runs_log = state_dir / "runs.jsonl"
        runs_log.touch(exist_ok=True)

        return cls(
            root=root,
            config_dir=config_dir,
            secrets_dir=secrets_dir,
            youtube_secrets_dir=youtube_secrets_dir,
            state_dir=state_dir,
            failed_dir=failed_dir,
            logs_dir=logs_dir,
            runs_dir=runs_dir,
            tts_cache_dir=tts_cache_dir,
            channel_config=channel_config,
            pipeline_config=pipeline_config,
            env_file=env_file,
            client_secret=youtube_secrets_dir / "client_secret.json",
            token_file=youtube_secrets_dir / "token.json",
            topic_history=topic_history,
            runs_log=runs_log,
        )

    @staticmethod
    def _copy_default(source: Path, destination: Path) -> None:
        if destination.exists():
            return
        if not source.exists():
            raise FileNotFoundError(f"Default configuration is missing: {source}")
        shutil.copyfile(source, destination)

    @staticmethod
    def atomic_json(path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    def append_run(self, value: dict[str, Any]) -> None:
        with self.runs_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")
