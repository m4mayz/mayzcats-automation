from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from mayzcats.history import HistoryStore
from mayzcats.models import Candidate
from mayzcats.pipeline import RunFinalizer
from mayzcats.storage import DriveLayout

spec = importlib.util.spec_from_file_location(
    "github_runner", Path(__file__).resolve().parents[1] / "scripts/github_runner.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_five_hour_slots_cross_midnight_and_manual_override():
    assert not runner.due({"last_slot": 4}, 24 * 3600)
    assert runner.due({"last_slot": 4}, 25 * 3600)
    assert runner.due({"last_slot": 4}, 24 * 3600, force=True)
    assert runner.due({}, 0)


def test_persist_exports_only_public_state_and_tracks_pending_run(tmp_path, monkeypatch):
    runtime, state = tmp_path / ".runtime", tmp_path / "state"
    monkeypatch.setattr(runner, "RUNTIME", runtime)
    monkeypatch.setattr(runner, "STATE", state)
    monkeypatch.setattr(runner, "SCHEDULE", state / "actions.json")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    runner.write_json(runtime / "attempt.json", {"slot": 42})
    runner.write_json(runtime / "state/topic_history.json", [{
        "subject": "slow blink", "angle": "trust", "published_at": "2026-09-09T00:00:00Z",
        "youtube_video_id": "published",
        "metadata": {"title": "Slow Blink", "run_id": "old", "private_data": "DO-NOT-COMMIT"},
    }])
    (runtime / "state/runs.jsonl").write_text(json.dumps({
        "run_id": "pending", "status": "failed", "error": "DO-NOT-COMMIT"
    }) + "\n")
    runner.write_json(runtime / "runs/pending/state.json", {
        "run_id": "pending", "updated_at": "2026-09-09"
    })
    runner.persist()
    assert "DO-NOT-COMMIT" not in (state / "topic_history.json").read_text()
    assert "DO-NOT-COMMIT" not in (state / "runs.jsonl").read_text()
    assert runner.read_json(state / "actions.json", {}) == {
        "last_slot": 42, "snapshot_run_id": "123", "pending_run": "pending",
    }


def test_auto_abandons_duplicate_checkpoint_and_starts_new_run(tmp_path, monkeypatch):
    runtime, state = tmp_path / ".runtime", tmp_path / "state"
    monkeypatch.setattr(runner, "RUNTIME", runtime)
    monkeypatch.setattr(runner, "STATE", state)
    monkeypatch.setattr(runner, "SCHEDULE", state / "actions.json")
    runner.write_json(state / "actions.json", {"pending_run": "duplicate"})
    runner.write_json(runtime / "runs/duplicate/state.json", {
        "run_id": "duplicate",
        "status": "failed",
        "error": "RuntimeError: Duplicate topic blocked: 'body language' matches 'tail communication'",
    })
    monkeypatch.setattr("mayzcats.youtube_upload.load_credentials", lambda *args, **kwargs: None)
    commands = []

    def completed(command):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", completed)

    assert runner.run("auto") == 0
    assert not (runtime / "runs/duplicate").exists()
    assert "--resume" not in commands[-1]


def test_success_archives_video_before_cleanup(tmp_path):
    defaults = Path(__file__).resolve().parents[1] / "config"
    layout = DriveLayout.bootstrap(tmp_path / "runtime", defaults)
    work = tmp_path / "render"
    work.mkdir()
    (work / "final.mp4").write_bytes(b"finished video")
    output = tmp_path / "output"
    RunFinalizer(layout, HistoryStore(layout.topic_history), output).success(
        run_id="archive-run", run_dir=work,
        candidate=Candidate("kneading", "comfort", "evergreen"),
        youtube_video_id="uploaded-id", metadata={},
    )
    assert (output / "archive-run.mp4").read_bytes() == b"finished video"
    assert not work.exists()
