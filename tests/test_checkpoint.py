from __future__ import annotations

from pathlib import Path

from mayzcats.checkpoint import RunCheckpoint, latest_failed_run
from mayzcats.storage import DriveLayout


def _defaults(tmp_path: Path) -> Path:
    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "channel.example.yaml").write_text("channel: {}\n", encoding="utf-8")
    (defaults / "pipeline.example.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    (defaults / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    return defaults


def test_checkpoint_persists_stage_artifacts_and_can_be_resumed(tmp_path: Path) -> None:
    layout = DriveLayout.bootstrap(tmp_path / "drive", _defaults(tmp_path))
    checkpoint = RunCheckpoint.create(layout, "run-1")

    checkpoint.save_json("script.json", {"script": "Cats knead blankets."})
    checkpoint.complete_stage("script")
    checkpoint.fail("music", "HTTP 403")

    reopened = RunCheckpoint.open(layout, "run-1")
    reopened.begin_resume()

    assert reopened.is_complete("script")
    assert reopened.load_json("script.json") == {"script": "Cats knead blankets."}
    assert reopened.state["status"] == "running"
    assert reopened.state["resume_count"] == 1


def test_latest_failed_run_ignores_successful_checkpoints(tmp_path: Path) -> None:
    layout = DriveLayout.bootstrap(tmp_path / "drive", _defaults(tmp_path))
    failed = RunCheckpoint.create(layout, "failed-run")
    failed.fail("render", "ffmpeg failed")
    successful = RunCheckpoint.create(layout, "successful-run")
    successful.finish("video-id")

    assert latest_failed_run(layout) == "failed-run"
