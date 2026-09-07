from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import DriveLayout


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunCheckpoint:
    def __init__(self, layout: DriveLayout, run_id: str, state: dict[str, Any]) -> None:
        self.layout = layout
        self.run_id = run_id
        self.directory = layout.runs_dir / run_id
        self.state_path = self.directory / "state.json"
        self.state = state

    @classmethod
    def create(cls, layout: DriveLayout, run_id: str) -> RunCheckpoint:
        directory = layout.runs_dir / run_id
        directory.mkdir(parents=True, exist_ok=False)
        now = _now()
        checkpoint = cls(
            layout,
            run_id,
            {
                "run_id": run_id,
                "status": "running",
                "stage": "start",
                "completed_stages": [],
                "resume_count": 0,
                "started_at": now,
                "updated_at": now,
            },
        )
        checkpoint._commit()
        return checkpoint

    @classmethod
    def open(cls, layout: DriveLayout, run_id: str) -> RunCheckpoint:
        directory = layout.runs_dir / run_id
        state_path = directory / "state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"Run checkpoint not found: {state_path}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("run_id") != run_id:
            raise ValueError(f"Checkpoint run ID does not match directory: {run_id}")
        return cls(layout, run_id, state)

    def begin_resume(self) -> None:
        if self.state.get("status") == "success":
            raise ValueError(f"Run {self.run_id} is already complete")
        self.state["status"] = "running"
        self.state["resume_count"] = int(self.state.get("resume_count", 0)) + 1
        self.state.pop("error", None)
        self._commit()

    def begin_stage(self, stage: str) -> None:
        self.state.update(status="running", stage=stage)
        self._commit()

    def complete_stage(self, stage: str) -> None:
        completed = list(self.state.get("completed_stages") or [])
        if stage not in completed:
            completed.append(stage)
        self.state.update(status="running", stage=stage, completed_stages=completed)
        self._commit()

    def is_complete(self, stage: str) -> bool:
        return stage in (self.state.get("completed_stages") or [])

    def fail(self, stage: str, error: str) -> None:
        self.state.update(status="failed", stage=stage, error=error)
        self._commit()

    def finish(self, youtube_video_id: str) -> None:
        self.state.update(
            status="success",
            stage="finalize",
            youtube_video_id=youtube_video_id,
        )
        self._commit()

    def save_json(self, name: str, value: Any) -> Path:
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        self.layout.atomic_json(path, value)
        return path

    def load_json(self, name: str) -> Any:
        return json.loads((self.directory / name).read_text(encoding="utf-8"))

    def remove(self) -> None:
        if self.directory.exists():
            shutil.rmtree(self.directory)

    def _commit(self) -> None:
        self.state["updated_at"] = _now()
        self.layout.atomic_json(self.state_path, self.state)


def latest_failed_run(layout: DriveLayout) -> str | None:
    candidates: list[tuple[str, str]] = []
    for state_path in layout.runs_dir.glob("*/state.json"):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state.get("status") != "failed":
            continue
        candidates.append((str(state.get("updated_at", "")), str(state.get("run_id", ""))))
    if not candidates:
        return None
    return max(candidates)[1]
