from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .checkpoint import RunCheckpoint, latest_failed_run
from .config import REQUIRED_SECRETS, Settings
from .dedup import DuplicateDetector, SentenceTransformerEmbedder
from .elevenlabs_tts import ElevenLabsClient
from .history import HistoryStore
from .llm import OpenAICompatibleClient
from .media_fetcher import MediaFetcher, PexelsProvider, PixabayProvider
from .models import (
    Candidate,
    HistoryEntry,
    MediaAsset,
    MusicTrack,
    PostPayload,
    ResearchBrief,
    ScriptPackage,
)
from .music_fetcher import REPO_MUSIC_DIR, MPTMusicLibrary
from .research import Researcher, TavilyClient
from .scene_planner import plan_scenes
from .script_writer import ScriptWriter
from .storage import DriveLayout
from .tts_cache import PersistentTTSCache
from .video_engine import MPTAdapter, VideoEngine
from .youtube_upload import YoutubeUploader, payload_from_file

LOGGER = logging.getLogger("mayzcats")


def _progress(message: str) -> None:
    LOGGER.info(message)


def redact(text: str, secrets: list[str]) -> str:
    result = text
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        result = result.replace(secret, "<redacted>")
    return result


class RunFinalizer:
    def __init__(self, layout: DriveLayout, history: HistoryStore) -> None:
        self.layout = layout
        self.history = history

    def success(
        self,
        *,
        run_id: str,
        run_dir: Path,
        candidate: Candidate,
        youtube_video_id: str,
        metadata: dict[str, Any],
        checkpoint: RunCheckpoint | None = None,
        now: datetime | None = None,
    ) -> None:
        if not youtube_video_id:
            raise ValueError("A YouTube video ID is required before history can be committed")
        now = now or datetime.now(UTC)
        privacy = str(metadata.get("privacy", "private"))
        complete = {
            **metadata,
            "run_id": run_id,
            "youtube_video_id": youtube_video_id,
            "youtube_url": f"https://youtu.be/{youtube_video_id}",
            "topic": candidate.subject,
            "angle": candidate.angle,
            "uploaded_at": now.isoformat(),
            "privacy": privacy,
            "status": "success",
        }
        self.history.commit_success(
            HistoryEntry(
                subject=candidate.subject,
                angle=candidate.angle,
                published_at=now,
                youtube_video_id=youtube_video_id,
                metadata=complete,
            )
        )
        self.layout.append_run(complete)
        if checkpoint is not None:
            checkpoint.finish(youtube_video_id)
        if Path(run_dir).exists():
            shutil.rmtree(run_dir)
        if checkpoint is not None:
            checkpoint.remove()

    def upload_failure(
        self,
        *,
        run_id: str,
        final_video: Path,
        post_payload: dict[str, Any],
        run_metadata: dict[str, Any],
        script: str,
        sources: list[dict[str, Any]],
        music: dict[str, Any],
        error: Exception,
        secrets: list[str],
    ) -> Path:
        package = self.layout.failed_dir / run_id
        package.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(final_video, package / "final.mp4")
        _write_json(package / "post_payload.json", post_payload)
        failed_run = {**run_metadata, "run_id": run_id, "status": "upload_failed"}
        _write_json(package / "run.json", failed_run)
        (package / "script.txt").write_text(script, encoding="utf-8")
        _write_json(package / "sources.json", sources)
        _write_json(package / "music.json", music)
        safe_error = redact(f"{type(error).__name__}: {error}", secrets)
        (package / "error.log").write_text(safe_error + "\n", encoding="utf-8")
        self.layout.append_run({**failed_run, "failed_package": str(package), "error": safe_error})
        self.history.record_failed_run()
        return package


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(destination)


class MayzCatsPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.history = HistoryStore(settings.layout.topic_history)
        network_attempts = int(settings.value("network.max_attempts", 3))
        llm = OpenAICompatibleClient(
            settings.secrets["OPENAI_BASE_URL"],
            settings.secrets["OPENAI_API_KEY"],
            settings.secrets["OPENAI_MODEL"],
            timeout=float(settings.value("network.llm_read_timeout_seconds", 180)),
            max_attempts=network_attempts,
            progress=_progress,
        )
        self.researcher = Researcher(
            TavilyClient(
                settings.secrets["TAVILY_API_KEY"],
                timeout=float(settings.value("network.tavily_read_timeout_seconds", 120)),
                max_attempts=network_attempts,
                progress=_progress,
            ),
            llm,
            minimum_sources=int(settings.value("research.min_sources", 3)),
            max_results=int(settings.value("research.max_results", 8)),
            progress=_progress,
        )
        from .topic_engine import CandidateGenerator

        self.candidate_generator = CandidateGenerator(
            llm, max_candidates=int(settings.value("topic.max_candidates", 20))
        )
        self.detector = DuplicateDetector(
            SentenceTransformerEmbedder(
                str(
                    settings.value(
                        "topic.embedding_model", "sentence-transformers/all-MiniLM-L6-v2"
                    )
                )
            ),
            float(settings.value("topic.subject_similarity_threshold", 0.90)),
        )
        self.script_writer = ScriptWriter(llm)
        self.tts = ElevenLabsClient(
            settings.elevenlabs_keys(),
            voice_id=str(settings.value("tts.voice_id", "cgSgspJ2msm6clMCkdW9")),
            model_id=str(settings.value("tts.model", "eleven_multilingual_v2")),
            speed=float(settings.value("tts.speed", 1.08)),
            output_format=str(settings.value("tts.output_format", "mp3_44100_128")),
        )
        self.tts_cache = PersistentTTSCache(settings.layout.tts_cache_dir)
        self.media = MediaFetcher(
            [
                PexelsProvider(settings.secrets["PEXELS_API_KEY"]),
                PixabayProvider(settings.secrets["PIXABAY_API_KEY"]),
            ],
            max_download_bytes=int(settings.value("media.max_download_bytes", 150_000_000)),
        )
        self.music = MPTMusicLibrary(
            REPO_MUSIC_DIR,
            excluded_files={str(name) for name in settings.value("music.excluded_files", [])},
        )
        self.video = VideoEngine(MPTAdapter(settings.mpt_root))
        self.uploader = YoutubeUploader(
            settings.layout.client_secret,
            settings.layout.token_file,
            chunk_size=int(settings.value("youtube.chunk_size_bytes", 8 * 1024 * 1024)),
            max_retries=int(settings.value("youtube.max_retries", 5)),
        )
        self.finalizer = RunFinalizer(settings.layout, self.history)

    def run(
        self,
        *,
        resume_id: str | None = None,
        force_rerender: bool = False,
    ) -> dict[str, Any]:
        if force_rerender and not resume_id:
            raise ValueError("force_rerender requires a resumed run")
        if resume_id:
            run_id = resume_id
            checkpoint = RunCheckpoint.open(self.settings.layout, run_id)
            checkpoint.begin_resume()
        else:
            run_id = str(uuid4())
            checkpoint = RunCheckpoint.create(self.settings.layout, run_id)

        run_dir = self.settings.work_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.settings.layout.logs_dir / f"{run_id}.log"
        _configure_logging(log_path)
        secrets = list(self.settings.secrets.values())
        stage = "start"
        candidate: Candidate | None = None
        script_package: ScriptPackage | None = None
        final_video: Path | None = None
        post_payload: PostPayload | None = None
        sources: list[dict[str, Any]] = []
        music_data: dict[str, Any] = {}
        metadata: dict[str, Any] = {
            "run_id": run_id,
            "started_at": checkpoint.state.get("started_at", datetime.now(UTC).isoformat()),
        }
        try:
            if resume_id:
                completed = checkpoint.state.get("completed_stages") or []
                _progress(f"[Resume] Run {run_id}")
                _progress(f"[Resume] Completed stages: {', '.join(completed) or 'none'}")
            else:
                _progress(f"[MayzCats] Run {run_id}")

            stage = "topic"
            if checkpoint.is_complete(stage):
                candidate = Candidate.from_dict(checkpoint.load_json("candidate.json"))
                _progress(f"[Resume] Topic: {candidate.subject}")
            else:
                checkpoint.begin_stage(stage)
                _progress("[Topic 1/3] Checking current cat trends with Tavily...")
                trend_context = self.researcher.discover_trends()
                _progress("[Topic 2/3] Generating candidate topics with the LLM...")
                candidates = self.candidate_generator.generate(trend_context=trend_context)
                recent = self.history.recent(
                    days=int(self.settings.value("topic.history_days", 90))
                )
                _progress(
                    f"[Topic 3/3] Checking {len(candidates)} candidates against "
                    f"{len(recent)} recent history entries..."
                )
                candidate = self.candidate_generator.choose_unused(
                    candidates, recent, self.detector
                )
                checkpoint.save_json("candidate.json", candidate.to_dict())
                checkpoint.complete_stage(stage)
                _progress(f"[Topic] Accepted: {candidate.subject} — {candidate.angle}")

            stage = "research"
            if checkpoint.is_complete(stage):
                brief = ResearchBrief.from_dict(checkpoint.load_json("research.json"))
                sources = [source.to_dict() for source in brief.sources]
                _progress(f"[Resume] Research: {len(sources)} sources")
            else:
                checkpoint.begin_stage(stage)
                _progress("[Research] Starting source collection and fact validation...")
                brief = self.researcher.research(candidate)
                sources = [source.to_dict() for source in brief.sources]
                checkpoint.save_json("research.json", brief.to_dict())
                checkpoint.complete_stage(stage)
                _progress(f"[Research] Complete; {len(sources)} source traces retained")

            stage = "script"
            if checkpoint.is_complete(stage):
                script_package = ScriptPackage.from_dict(checkpoint.load_json("script.json"))
                _progress(
                    f"[Resume] Script: {len(script_package.script.split())} words"
                )
            else:
                checkpoint.begin_stage(stage)
                _progress("[Script] Writing the grounded narration and metadata...")
                script_package = self.script_writer.write(candidate, brief)
                checkpoint.save_json("script.json", script_package.to_dict())
                checkpoint.complete_stage(stage)
                _progress(
                    f"[Script] Draft ready ({len(script_package.script.split())} words)"
                )

            stage = "media"
            desired = min(
                int(self.settings.value("media.desired_scenes", 9)),
                len(script_package.beats),
            )
            minimum_assets = min(
                desired, int(self.settings.value("media.minimum_assets", 4))
            )
            downloaded_assets: list[MediaAsset] = []
            if checkpoint.is_complete(stage):
                downloaded_assets = [
                    MediaAsset.from_dict(item)
                    for item in checkpoint.load_json("media.json")
                ]
                if not downloaded_assets or any(
                    not asset.local_path or not asset.local_path.exists()
                    for asset in downloaded_assets
                ):
                    downloaded_assets = []
                else:
                    _progress(f"[Resume] Media: {len(downloaded_assets)} cached assets")
            if not downloaded_assets:
                checkpoint.begin_stage(stage)
                _progress(
                    f"[Media 1/2] Searching Pexels and Pixabay for {desired} scene assets..."
                )
                assets = self.media.find(
                    script_package.search_terms,
                    count=desired,
                    minimum=minimum_assets,
                )
                for index, asset in enumerate(assets, start=1):
                    _progress(
                        f"[Media 2/2] Downloading asset {index}/{len(assets)} "
                        f"from {asset.provider}..."
                    )
                    downloaded_assets.append(
                        self.media.download(asset, checkpoint.directory / "media")
                    )
                checkpoint.save_json(
                    "media.json", [asset.to_dict() for asset in downloaded_assets]
                )
                checkpoint.complete_stage(stage)
                _progress(f"[Media] {len(downloaded_assets)} assets cached in Drive")

            stage = "music"
            music: MusicTrack | None = None
            if checkpoint.is_complete(stage):
                music = MusicTrack.from_dict(checkpoint.load_json("music.json"))
                if not music.local_path or not music.local_path.exists():
                    music = None
                else:
                    _progress(f"[Resume] Music: {music.title}")
            if music is None:
                checkpoint.begin_stage(stage)
                _progress("[Music] Selecting and validating a bundled MoneyPrinterTurbo track...")
                music = self.music.prepare(run_id, checkpoint.directory / "music")
                music_data = music.to_dict()
                checkpoint.save_json("music.json", music_data)
                checkpoint.complete_stage(stage)
                _progress(f"[Music] Ready before TTS: {music.title}")
            else:
                music_data = music.to_dict()

            stage = "tts"
            narration = None
            if checkpoint.is_complete(stage):
                from .models import Narration

                narration = Narration.from_dict(checkpoint.load_json("narration.json"))
                if not narration.audio_path.exists():
                    narration = None
                else:
                    _progress(
                        f"[Resume] TTS: reusing cached narration ({narration.duration:.1f}s)"
                    )
            if narration is None:
                checkpoint.begin_stage(stage)
                minimum = float(self.settings.value("script.min_duration_seconds", 35))
                maximum = float(self.settings.value("script.max_duration_seconds", 55))
                max_attempts = int(self.settings.value("script.max_tts_attempts", 3))
                for attempt in range(1, max_attempts + 1):
                    _progress(f"[TTS] Narration attempt {attempt}/{max_attempts}...")
                    narration = self.tts_cache.get_or_create(
                        script_package.script, self.tts
                    )
                    if narration.cache_hit:
                        _progress(
                            f"[TTS] Cache hit; ElevenLabs was not called ({narration.duration:.1f}s)"
                        )
                    else:
                        _progress(
                            f"[TTS] ElevenLabs key #{narration.key_index}: "
                            f"{narration.duration:.1f}s; saved to Drive cache"
                        )
                    if minimum <= narration.duration <= maximum:
                        break
                    if attempt == max_attempts:
                        raise RuntimeError(
                            f"Narration remained outside {minimum:.0f}-{maximum:.0f}s "
                            f"after {max_attempts} attempts"
                        )
                    script_package = self.script_writer.revise_for_duration(
                        script_package,
                        narration.duration,
                        minimum=minimum,
                        maximum=maximum,
                    )
                    checkpoint.save_json("script.json", script_package.to_dict())
                checkpoint.save_json("narration.json", narration.to_dict())
                checkpoint.complete_stage(stage)

            scenes = plan_scenes(
                duration=narration.duration,
                beats=script_package.beats[:desired],
                assets=downloaded_assets,
            )
            _progress(f"[Media] {len(scenes)} adaptive scenes prepared")

            stage = "render"
            rendered_duration = 0.0
            checkpoint_video = checkpoint.directory / "final.mp4"
            if (
                checkpoint.is_complete(stage)
                and checkpoint_video.exists()
                and not force_rerender
            ):
                final_video = checkpoint_video
                rendered_duration = float(checkpoint.load_json("render.json")["duration"])
                _progress(
                    f"[Resume] Render: reusing final.mp4 ({rendered_duration:.1f}s)"
                )
            else:
                checkpoint.begin_stage(stage)
                if force_rerender:
                    _progress(
                        "[Resume] Render override: rebuilding video with cached media and TTS..."
                    )
                _progress("[Render] Starting base composition and final subtitle/music pass...")
                local_video, rendered_duration = self.video.render(
                    run_id=run_id,
                    run_dir=run_dir,
                    scenes=scenes,
                    narration=narration,
                    package=script_package,
                    music=music,
                    music_volume=float(self.settings.value("music.volume", 0.08)),
                )
                _copy_atomic(local_video, checkpoint_video)
                final_video = checkpoint_video
                checkpoint.save_json("render.json", {"duration": rendered_duration})
                checkpoint.complete_stage(stage)
                _progress(f"[Video] 1080x1920 / 30 fps / {rendered_duration:.1f}s")

            description = (
                script_package.description.rstrip()
                + "\n\n"
                + " ".join(script_package.hashtags)
            )
            privacy = str(self.settings.value("youtube.privacy", "private")).lower()
            post_payload = PostPayload(
                title=script_package.title,
                description=description,
                tags=script_package.tags,
                category_id="15",
                privacy=privacy,
                made_for_kids=False,
            )
            metadata.update(
                {
                    "title": script_package.title,
                    "description": description,
                    "hashtags": script_package.hashtags,
                    "tags": script_package.tags,
                    "script": script_package.script,
                    "sources": sources,
                    "music_source": music_data,
                    "media_sources": [asset.to_dict() for asset in downloaded_assets],
                    "duration": rendered_duration,
                    "privacy": privacy,
                    "topic": candidate.subject,
                    "angle": candidate.angle,
                }
            )
            checkpoint.save_json("post_payload.json", post_payload.to_dict())
            checkpoint.save_json("metadata.json", metadata)

            stage = "upload"
            youtube_video_id = ""
            if checkpoint.is_complete(stage):
                youtube_video_id = str(
                    checkpoint.load_json("upload.json").get("youtube_video_id", "")
                )
                if youtube_video_id:
                    _progress(f"[Resume] Upload already completed: {youtube_video_id}")
            if not youtube_video_id:
                checkpoint.begin_stage(stage)
                _progress(f"[YouTube] Uploading as {privacy.title()}...")
                youtube_video_id = self.uploader.upload(final_video, post_payload)
                checkpoint.save_json(
                    "upload.json", {"youtube_video_id": youtube_video_id}
                )
                checkpoint.complete_stage(stage)

            metadata["youtube_video_id"] = youtube_video_id
            stage = "finalize"
            checkpoint.begin_stage(stage)
            self.finalizer.success(
                run_id=run_id,
                run_dir=run_dir,
                candidate=candidate,
                youtube_video_id=youtube_video_id,
                metadata=metadata,
                checkpoint=checkpoint,
            )
            failed_package = self.settings.layout.failed_dir / run_id
            if failed_package.exists():
                shutil.rmtree(failed_package)
            _progress(
                f"[YouTube] SUCCESS ({privacy.title()}): https://youtu.be/{youtube_video_id}"
            )
            return {
                "run_id": run_id,
                "youtube_video_id": youtube_video_id,
                "privacy": privacy,
                "title": script_package.title,
            }
        except Exception as exc:
            safe_error = redact(f"{type(exc).__name__}: {exc}", secrets)
            if checkpoint.directory.exists():
                checkpoint.fail(stage, safe_error)
            LOGGER.error("[FAILED] Stage %s: %s", stage, safe_error)
            LOGGER.error("[FAILED] Run ID: %s", run_id)
            LOGGER.error("[FAILED] Resume with: --resume %s", run_id)
            LOGGER.error("[FAILED] Detailed log: %s", log_path)
            if (
                stage == "upload"
                and final_video
                and final_video.exists()
                and candidate
                and post_payload
                and script_package
            ):
                package = self.finalizer.upload_failure(
                    run_id=run_id,
                    final_video=final_video,
                    post_payload=post_payload.to_dict(),
                    run_metadata={**metadata, "stage": stage},
                    script=script_package.script,
                    sources=sources,
                    music=music_data,
                    error=exc,
                    secrets=secrets,
                )
                LOGGER.error("[YouTube] Complete retry package: %s", package)
            else:
                self.settings.layout.append_run(
                    {**metadata, "status": "failed", "stage": stage, "error": safe_error}
                )
            raise RuntimeError(
                f"MayzCats failed at stage '{stage}': {safe_error}. Log: {log_path}"
            ) from None


def _configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(stream)


def build_settings(drive_root: Path, mpt_root: Path, work_root: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    layout = DriveLayout.bootstrap(drive_root, project_root / "config")
    settings = Settings.load(layout, work_root=work_root, mpt_root=mpt_root)
    settings.require_secrets(*REQUIRED_SECRETS)
    return settings


def retry_failed_upload(drive_root: Path, run_id: str) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[2]
    layout = DriveLayout.bootstrap(drive_root, project_root / "config")
    package = layout.failed_dir / run_id
    if not package.is_dir():
        raise FileNotFoundError(f"Failed-upload package not found: {package}")
    settings = Settings.load(layout)
    uploader = YoutubeUploader(layout.client_secret, layout.token_file)
    payload = payload_from_file(package / "post_payload.json")
    video_id = uploader.upload(package / "final.mp4", payload)
    run_data = json.loads((package / "run.json").read_text(encoding="utf-8"))
    candidate = Candidate(
        subject=run_data["topic"], angle=run_data["angle"], kind="recovered"
    )
    finalizer = RunFinalizer(layout, HistoryStore(layout.topic_history))
    temporary_run = settings.work_root / f"retry-{run_id}"
    temporary_run.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package / "final.mp4", temporary_run / "final.mp4")
    checkpoint = None
    with suppress(FileNotFoundError):
        checkpoint = RunCheckpoint.open(layout, run_id)
    finalizer.success(
        run_id=run_id,
        run_dir=temporary_run,
        candidate=candidate,
        youtube_video_id=video_id,
        metadata={**run_data, "privacy": payload.privacy, "recovered_from": str(package)},
        checkpoint=checkpoint,
    )
    if package.exists():
        shutil.rmtree(package)
    return {"run_id": run_id, "youtube_video_id": video_id, "privacy": payload.privacy}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MayzCats V1")
    parser.add_argument(
        "--drive-root",
        type=Path,
        default=Path("/content/drive/MyDrive/MayzCats-Automation"),
    )
    parser.add_argument(
        "--mpt-root",
        type=Path,
        default=Path("/content/mayzcats-project/vendor/MoneyPrinterTurbo"),
    )
    parser.add_argument("--work-root", type=Path, default=Path("/content/mayzcats/runs"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", metavar="RUN_ID")
    mode.add_argument("--resume-latest", action="store_true")
    mode.add_argument("--retry-upload", metavar="RUN_ID")
    parser.add_argument(
        "--rerender",
        action="store_true",
        help="rebuild the video while reusing completed paid stages from a resumed run",
    )
    args = parser.parse_args(argv)
    if args.rerender and not (args.resume or args.resume_latest):
        parser.error("--rerender requires --resume or --resume-latest")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.retry_upload:
        result = retry_failed_upload(args.drive_root, args.retry_upload)
    else:
        settings = build_settings(args.drive_root, args.mpt_root, args.work_root)
        resume_id = args.resume
        if args.resume_latest:
            resume_id = latest_failed_run(settings.layout)
            if not resume_id:
                raise RuntimeError("No failed MayzCats checkpoint is available to resume")
        result = MayzCatsPipeline(settings).run(
            resume_id=resume_id,
            force_rerender=args.rerender,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
