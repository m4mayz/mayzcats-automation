from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mayzcats.history import HistoryStore
from mayzcats.models import HistoryEntry
from mayzcats.storage import DriveLayout


def test_bootstrap_preserves_existing_configuration(tmp_path: Path) -> None:
    defaults = tmp_path / "defaults"
    defaults.mkdir()
    (defaults / "channel.example.yaml").write_text("channel: default\n", encoding="utf-8")
    (defaults / "pipeline.example.yaml").write_text("pipeline: default\n", encoding="utf-8")
    (defaults / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    root = tmp_path / "drive"
    (root / "config").mkdir(parents=True)
    (root / "config" / "channel.yaml").write_text("channel: mine\n", encoding="utf-8")

    layout = DriveLayout.bootstrap(root, defaults)

    assert layout.channel_config.read_text(encoding="utf-8") == "channel: mine\n"
    assert layout.pipeline_config.read_text(encoding="utf-8") == "pipeline: default\n"
    assert layout.env_file.read_text(encoding="utf-8") == "OPENAI_API_KEY=\n"
    assert json.loads(layout.topic_history.read_text(encoding="utf-8")) == []


def test_bootstrap_accepts_project_root_env_example(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    defaults = project_root / "config"
    defaults.mkdir(parents=True)
    (defaults / "channel.example.yaml").write_text("channel: {}\n", encoding="utf-8")
    (defaults / "pipeline.example.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    (project_root / ".env.example").write_text("TAVILY_API_KEY=\n", encoding="utf-8")

    layout = DriveLayout.bootstrap(tmp_path / "drive", defaults)

    assert layout.env_file.read_text(encoding="utf-8") == "TAVILY_API_KEY=\n"


def test_history_filters_90_days_and_commits_success_atomically(tmp_path: Path) -> None:
    history_path = tmp_path / "topic_history.json"
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    entries = [
        HistoryEntry("Recent", "angle", now - timedelta(days=89), "vid-recent"),
        HistoryEntry("Old", "angle", now - timedelta(days=91), "vid-old"),
    ]
    history_path.write_text(json.dumps([entry.to_dict() for entry in entries]), encoding="utf-8")
    store = HistoryStore(history_path)

    assert [entry.subject for entry in store.recent(now=now, days=90)] == ["Recent"]

    new_entry = HistoryEntry("New", "fresh angle", now, "vid-new")
    store.commit_success(new_entry)
    saved = json.loads(history_path.read_text(encoding="utf-8"))
    assert [item["youtube_video_id"] for item in saved] == [
        "vid-recent",
        "vid-old",
        "vid-new",
    ]
    assert not history_path.with_suffix(".json.tmp").exists()


def test_failed_run_does_not_mutate_history(tmp_path: Path) -> None:
    history_path = tmp_path / "topic_history.json"
    history_path.write_text("[]", encoding="utf-8")
    store = HistoryStore(history_path)

    store.record_failed_run()

    assert history_path.read_text(encoding="utf-8") == "[]"
