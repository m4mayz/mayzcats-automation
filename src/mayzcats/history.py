from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import HistoryEntry
from .storage import DriveLayout


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def all(self) -> list[HistoryEntry]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        if not isinstance(raw, list):
            raise ValueError("Topic history must be a JSON array")
        return [HistoryEntry.from_dict(item) for item in raw]

    def recent(self, *, now: datetime | None = None, days: int = 90) -> list[HistoryEntry]:
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        cutoff = now - timedelta(days=days)
        return [entry for entry in self.all() if entry.published_at >= cutoff]

    def commit_success(self, entry: HistoryEntry) -> None:
        entries = self.all()
        if not any(item.youtube_video_id == entry.youtube_video_id for item in entries):
            entries.append(entry)
        DriveLayout.atomic_json(self.path, [item.to_dict() for item in entries])

    def record_failed_run(self) -> None:
        """Deliberately leave topic history unchanged for a failed run."""
