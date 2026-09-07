from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class Candidate:
    subject: str
    angle: str
    kind: str
    rationale: str = ""
    search_queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candidate:
        return cls(
            subject=str(data["subject"]),
            angle=str(data["angle"]),
            kind=str(data["kind"]),
            rationale=str(data.get("rationale", "")),
            search_queries=list(data.get("search_queries") or []),
        )


@dataclass(slots=True)
class HistoryEntry:
    subject: str
    angle: str
    published_at: datetime
    youtube_video_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HistoryEntry:
        published_at = data["published_at"]
        if isinstance(published_at, str):
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        return cls(
            subject=str(data["subject"]),
            angle=str(data["angle"]),
            published_at=published_at,
            youtube_video_id=str(data["youtube_video_id"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class SourceTrace:
    title: str
    url: str
    content: str
    score: float
    retrieved_at: str

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceTrace:
        return cls(
            title=str(data["title"]),
            url=str(data["url"]),
            content=str(data["content"]),
            score=float(data["score"]),
            retrieved_at=str(data["retrieved_at"]),
        )


@dataclass(slots=True)
class ResearchBrief:
    summary: str
    claims: list[str]
    sources: list[SourceTrace]
    medical: bool = False
    vet_disclaimer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchBrief:
        return cls(
            summary=str(data["summary"]),
            claims=[str(item) for item in data.get("claims", [])],
            sources=[SourceTrace.from_dict(item) for item in data.get("sources", [])],
            medical=bool(data.get("medical", False)),
            vet_disclaimer=data.get("vet_disclaimer"),
        )


@dataclass(slots=True)
class ScriptPackage:
    script: str
    title: str
    description: str
    hashtags: list[str]
    tags: list[str]
    hook_text: str
    hook_keyword: str
    search_terms: list[str]
    beats: list[str]
    mood: str
    medical: bool

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScriptPackage:
        return cls(
            script=str(data["script"]),
            title=str(data["title"]),
            description=str(data["description"]),
            hashtags=[str(item) for item in data.get("hashtags", [])],
            tags=[str(item) for item in data.get("tags", [])],
            hook_text=str(data["hook_text"]),
            hook_keyword=str(data["hook_keyword"]),
            search_terms=[str(item) for item in data.get("search_terms", [])],
            beats=[str(item) for item in data.get("beats", [])],
            mood=str(data["mood"]),
            medical=bool(data.get("medical", False)),
        )


@dataclass(slots=True)
class WordTiming:
    text: str
    start: float
    end: float


@dataclass(slots=True)
class Narration:
    audio_path: Path
    duration: float
    words: list[WordTiming]
    key_index: int
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Narration:
        return cls(
            audio_path=Path(data["audio_path"]),
            duration=float(data["duration"]),
            words=[
                WordTiming(str(item["text"]), float(item["start"]), float(item["end"]))
                for item in data.get("words", [])
            ],
            key_index=int(data.get("key_index", 0)),
            cache_hit=bool(data.get("cache_hit", True)),
        )


@dataclass(slots=True)
class MediaAsset:
    asset_id: str
    provider: str
    kind: str
    download_url: str
    source_url: str
    creator: str
    license_name: str
    license_url: str
    width: int
    height: int
    duration: float | None
    score: float = 0.0
    local_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaAsset:
        local_path = data.get("local_path")
        return cls(
            asset_id=str(data["asset_id"]),
            provider=str(data["provider"]),
            kind=str(data["kind"]),
            download_url=str(data["download_url"]),
            source_url=str(data["source_url"]),
            creator=str(data["creator"]),
            license_name=str(data["license_name"]),
            license_url=str(data["license_url"]),
            width=int(data["width"]),
            height=int(data["height"]),
            duration=float(data["duration"]) if data.get("duration") is not None else None,
            score=float(data.get("score", 0.0)),
            local_path=Path(local_path) if local_path else None,
        )


@dataclass(slots=True)
class MusicTrack:
    title: str
    creator: str
    download_url: str
    source_url: str
    license_name: str
    license_url: str
    retrieved_at: str
    local_path: Path | None = None
    provider: str = "external"
    sha256: str = ""
    license_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MusicTrack:
        local_path = data.get("local_path")
        return cls(
            title=str(data["title"]),
            creator=str(data["creator"]),
            download_url=str(data["download_url"]),
            source_url=str(data["source_url"]),
            license_name=str(data["license_name"]),
            license_url=str(data["license_url"]),
            retrieved_at=str(data["retrieved_at"]),
            local_path=Path(local_path) if local_path else None,
            provider=str(data.get("provider", "external")),
            sha256=str(data.get("sha256", "")),
            license_status=str(data.get("license_status", "")),
        )


@dataclass(slots=True)
class Scene:
    asset: MediaAsset
    start: float
    end: float
    beat_index: int
    local_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass(slots=True)
class PostPayload:
    title: str
    description: str
    tags: list[str]
    category_id: str = "15"
    privacy: str = "private"
    made_for_kids: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))
