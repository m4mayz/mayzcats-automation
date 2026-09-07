from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mayzcats.checkpoint import RunCheckpoint
from mayzcats.history import HistoryStore
from mayzcats.models import (
    Candidate,
    MediaAsset,
    MusicTrack,
    Narration,
    PostPayload,
    ResearchBrief,
    ScriptPackage,
    SourceTrace,
    WordTiming,
)
from mayzcats.pipeline import MayzCatsPipeline, RunFinalizer, parse_args
from mayzcats.storage import DriveLayout
from mayzcats.youtube_upload import build_video_body


def _payload(privacy: str = "private") -> PostPayload:
    return PostPayload(
        title="Why Cats Chirp",
        description="A sourced explanation.\n\n#shorts #cats",
        tags=["cats", "cat lovers", "pets", "cute animals", "cat chirping"],
        category_id="15",
        privacy=privacy,
        made_for_kids=False,
    )


def test_youtube_body_supports_configured_private_or_public_privacy() -> None:
    body = build_video_body(_payload("private"))
    assert body["snippet"]["categoryId"] == "15"
    assert body["status"] == {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    public = build_video_body(_payload("public"))
    assert public["status"]["privacyStatus"] == "public"
    with pytest.raises(ValueError, match="privacy"):
        build_video_body(_payload("friends-only"))


def test_success_commits_history_then_removes_local_run(tmp_path: Path) -> None:
    layout = DriveLayout.bootstrap(tmp_path / "drive", _defaults(tmp_path))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "final.mp4").write_bytes(b"video")
    finalizer = RunFinalizer(layout, HistoryStore(layout.topic_history))
    candidate = Candidate("Cat chirping", "why cats chirp at birds", "evergreen")

    finalizer.success(
        run_id="run1",
        run_dir=run_dir,
        candidate=candidate,
        youtube_video_id="abc123",
        metadata={"duration": 42.0},
        now=datetime(2026, 9, 2, tzinfo=UTC),
    )

    saved = json.loads(layout.topic_history.read_text(encoding="utf-8"))
    assert saved[0]["youtube_video_id"] == "abc123"
    assert not run_dir.exists()


def test_success_marks_topic_used_before_writing_secondary_run_log(tmp_path: Path) -> None:
    events: list[str] = []

    class SpyLayout:
        def append_run(self, value: dict) -> None:
            events.append("run-log")

    class SpyHistory:
        def commit_success(self, entry) -> None:
            events.append("history")

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    finalizer = RunFinalizer(SpyLayout(), SpyHistory())

    finalizer.success(
        run_id="run-order",
        run_dir=run_dir,
        candidate=Candidate("Subject", "Angle", "evergreen"),
        youtube_video_id="uploaded-id",
        metadata={},
        now=datetime(2026, 9, 2, tzinfo=UTC),
    )

    assert events == ["history", "run-log"]


def test_upload_failure_writes_complete_reusable_package_without_history(tmp_path: Path) -> None:
    layout = DriveLayout.bootstrap(tmp_path / "drive", _defaults(tmp_path))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    final = run_dir / "final.mp4"
    final.write_bytes(b"video")
    finalizer = RunFinalizer(layout, HistoryStore(layout.topic_history))

    package = finalizer.upload_failure(
        run_id="run2",
        final_video=final,
        post_payload=_payload().to_dict(),
        run_metadata={"topic": "Cat chirping"},
        script="Cats chirp.",
        sources=[{"url": "https://vet.example/cats"}],
        music={"license": "CC BY 4.0"},
        error=RuntimeError("token sk-secret-value failed"),
        secrets=["sk-secret-value"],
    )

    assert {path.name for path in package.iterdir()} == {
        "final.mp4",
        "post_payload.json",
        "run.json",
        "script.txt",
        "sources.json",
        "music.json",
        "error.log",
    }
    assert "sk-secret-value" not in (package / "error.log").read_text(encoding="utf-8")
    assert json.loads(layout.topic_history.read_text(encoding="utf-8")) == []


def test_pipeline_prepares_media_and_mpt_music_before_paid_tts(tmp_path: Path) -> None:
    layout = DriveLayout.bootstrap(tmp_path / "drive", _defaults(tmp_path))

    class Settings:
        secrets: dict[str, str] = {}
        work_root = tmp_path / "work"
        mpt_root = tmp_path / "MoneyPrinterTurbo"

        def __init__(self) -> None:
            self.layout = layout

        def value(self, path: str, default=None):
            return {
                "media.desired_scenes": 1,
                "media.minimum_assets": 1,
            }.get(path, default)

    candidate = Candidate("Cat paws", "why cats knead", "evergreen")
    brief = ResearchBrief(
        summary="summary",
        claims=["claim"],
        sources=[SourceTrace("source", "https://example.test", "content", 1.0, "now")],
    )
    script = ScriptPackage(
        script="Cats knead blankets.",
        title="Why Cats Knead",
        description="Description",
        hashtags=["#shorts", "#cats", "#catfacts"],
        tags=["cats"],
        hook_text="Cats knead for a reason",
        hook_keyword="knead",
        search_terms=["cat kneading"],
        beats=["cat kneading"],
        mood="warm",
        medical=False,
    )
    asset = MediaAsset(
        asset_id="a",
        provider="pexels",
        kind="video",
        download_url="https://cdn.test/a.mp4",
        source_url="https://pexels.test/a",
        creator="creator",
        license_name="license",
        license_url="https://license.test",
        width=1080,
        height=1920,
        duration=5,
    )

    class History:
        def recent(self, days: int):
            return []

    class Researcher:
        def discover_trends(self):
            return ""

        def research(self, selected):
            return brief

    class Candidates:
        def generate(self, trend_context: str):
            return [candidate]

        def choose_unused(self, candidates, recent, detector):
            return candidate

    class Writer:
        def write(self, selected, research):
            return script

    class Media:
        def find(self, terms, *, count, minimum):
            return [asset]

        def download(self, selected, directory):
            directory.mkdir(parents=True, exist_ok=True)
            selected.local_path = directory / "a.mp4"
            selected.local_path.write_bytes(b"video")
            return selected

    class Music:
        def prepare(self, run_id, directory):
            raise RuntimeError("music validation failed")

    class PaidTTS:
        calls = 0

        def get_or_create(self, text, client):
            self.calls += 1
            raise AssertionError("TTS must not run before music is ready")

    pipeline = MayzCatsPipeline.__new__(MayzCatsPipeline)
    pipeline.settings = Settings()
    pipeline.history = History()
    pipeline.researcher = Researcher()
    pipeline.candidate_generator = Candidates()
    pipeline.detector = object()
    pipeline.script_writer = Writer()
    pipeline.media = Media()
    pipeline.music = Music()
    pipeline.tts_cache = PaidTTS()
    pipeline.tts = object()

    with pytest.raises(RuntimeError, match="stage 'music'"):
        pipeline.run()

    assert pipeline.tts_cache.calls == 0


@pytest.mark.parametrize(
    ("force_rerender", "expected_render_calls"),
    [(False, 0), (True, 1)],
)
def test_pipeline_resume_reuses_paid_tts_and_optionally_rerenders_video(
    tmp_path: Path, force_rerender: bool, expected_render_calls: int
) -> None:
    layout = DriveLayout.bootstrap(tmp_path / "drive", _defaults(tmp_path))
    checkpoint = RunCheckpoint.create(layout, "resume-run")
    candidate = Candidate("Cat paws", "why cats knead", "evergreen")
    brief = ResearchBrief(
        summary="summary",
        claims=["claim"],
        sources=[SourceTrace("source", "https://example.test", "content", 1.0, "now")],
    )
    script = ScriptPackage(
        script="Cats knead blankets.",
        title="Why Cats Knead",
        description="Description",
        hashtags=["#shorts", "#cats", "#catfacts"],
        tags=["cats"],
        hook_text="Cats knead for a reason",
        hook_keyword="knead",
        search_terms=["cat kneading"],
        beats=["cat kneading"],
        mood="warm",
        medical=False,
    )
    media_path = checkpoint.directory / "media" / "a.mp4"
    media_path.parent.mkdir()
    media_path.write_bytes(b"video")
    asset = MediaAsset(
        asset_id="a",
        provider="pexels",
        kind="video",
        download_url="https://cdn.test/a.mp4",
        source_url="https://pexels.test/a",
        creator="creator",
        license_name="license",
        license_url="https://license.test",
        width=1080,
        height=1920,
        duration=5,
        local_path=media_path,
    )
    music_path = checkpoint.directory / "music" / "output000.mp3"
    music_path.parent.mkdir()
    music_path.write_bytes(b"music")
    music = MusicTrack(
        title="output000.mp3",
        creator="MPT",
        download_url="https://github.test/output000.mp3",
        source_url="https://github.test/output000.mp3",
        license_name="unverified",
        license_url="https://github.test/readme",
        retrieved_at="now",
        local_path=music_path,
        provider="moneyprinterturbo_builtin",
    )
    audio_path = layout.tts_cache_dir / "hash" / "narration.mp3"
    audio_path.parent.mkdir()
    audio_path.write_bytes(b"audio")
    narration = Narration(audio_path, 42.0, [WordTiming("Cats", 0.0, 0.5)], 1, True)
    final_path = checkpoint.directory / "final.mp4"
    final_path.write_bytes(b"rendered")
    artifacts = {
        "candidate.json": candidate.to_dict(),
        "research.json": brief.to_dict(),
        "script.json": script.to_dict(),
        "media.json": [asset.to_dict()],
        "music.json": music.to_dict(),
        "narration.json": narration.to_dict(),
        "render.json": {"duration": 42.0},
    }
    stage_files = [
        ("topic", "candidate.json"),
        ("research", "research.json"),
        ("script", "script.json"),
        ("media", "media.json"),
        ("music", "music.json"),
        ("tts", "narration.json"),
        ("render", "render.json"),
    ]
    for stage, filename in stage_files:
        checkpoint.save_json(filename, artifacts[filename])
        checkpoint.complete_stage(stage)
    checkpoint.fail("upload", "temporary upload error")

    class Settings:
        secrets: dict[str, str] = {}
        work_root = tmp_path / "work"
        mpt_root = tmp_path / "MoneyPrinterTurbo"

        def __init__(self) -> None:
            self.layout = layout

        def value(self, path: str, default=None):
            return {
                "media.desired_scenes": 1,
                "media.minimum_assets": 1,
                "youtube.privacy": "public",
            }.get(path, default)

    class MustNotRun:
        def __getattr__(self, name):
            raise AssertionError(f"resumed completed dependency was called: {name}")

    class Video:
        def __init__(self) -> None:
            self.calls = 0

        def render(self, **kwargs):
            self.calls += 1
            assert kwargs["narration"].audio_path == audio_path
            rerendered = tmp_path / "rerendered.mp4"
            rerendered.write_bytes(b"new subtitles")
            return rerendered, 42.0

    class Uploader:
        def upload(self, video_path, payload):
            assert video_path == final_path
            assert payload.privacy == "public"
            return "public-video-id"

    pipeline = MayzCatsPipeline.__new__(MayzCatsPipeline)
    pipeline.settings = Settings()
    pipeline.history = HistoryStore(layout.topic_history)
    pipeline.researcher = MustNotRun()
    pipeline.candidate_generator = MustNotRun()
    pipeline.detector = MustNotRun()
    pipeline.script_writer = MustNotRun()
    pipeline.media = MustNotRun()
    pipeline.music = MustNotRun()
    pipeline.tts_cache = MustNotRun()
    pipeline.tts = MustNotRun()
    video = Video()
    pipeline.video = video
    pipeline.uploader = Uploader()
    pipeline.finalizer = RunFinalizer(layout, pipeline.history)

    result = pipeline.run(resume_id="resume-run", force_rerender=force_rerender)

    assert result["privacy"] == "public"
    assert result["youtube_video_id"] == "public-video-id"
    assert video.calls == expected_render_calls
    assert not checkpoint.directory.exists()


def test_cli_accepts_rerender_for_a_resumed_run() -> None:
    args = parse_args(["--resume", "run-123", "--rerender"])

    assert args.resume == "run-123"
    assert args.rerender is True


def _defaults(tmp_path: Path) -> Path:
    defaults = tmp_path / "defaults"
    defaults.mkdir(exist_ok=True)
    (defaults / "channel.example.yaml").write_text("channel: {}\n", encoding="utf-8")
    (defaults / "pipeline.example.yaml").write_text("pipeline: {}\n", encoding="utf-8")
    (defaults / ".env.example").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    return defaults
