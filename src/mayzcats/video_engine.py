from __future__ import annotations

import json
import math
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import MusicTrack, Narration, Scene, ScriptPackage
from .subtitle_engine import AssSubtitleEngine


def validate_probe(data: dict[str, Any]) -> float:
    streams = data.get("streams") or []
    videos = [stream for stream in streams if stream.get("codec_type") == "video"]
    audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
    if not videos:
        raise ValueError("Rendered file has no video stream")
    video = videos[0]
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (1080, 1920):
        raise ValueError("Rendered video must be exactly 1080x1920")
    rate = str(video.get("r_frame_rate", "0/1")).split("/", 1)
    fps = float(rate[0]) / float(rate[1])
    if abs(fps - 30.0) > 0.01:
        raise ValueError(f"Rendered video must be 30 fps, got {fps:.3f}")
    if not audios:
        raise ValueError("Rendered file has no audio stream")
    duration = float((data.get("format") or {}).get("duration", 0.0))
    if duration <= 0:
        raise ValueError("Rendered file has no positive duration")
    return duration


def probe_video(path: Path, ffprobe: str = "ffprobe") -> dict[str, Any]:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class MPTAdapter:
    def __init__(self, mpt_root: Path, *, uv_executable: str = "uv") -> None:
        self.mpt_root = Path(mpt_root)
        self.uv_executable = uv_executable

    def build_command(
        self,
        *,
        script: str,
        narration: Path,
        clips: list[Path],
        task_id: str,
        max_clip_duration: int,
    ) -> list[str]:
        if not clips:
            raise ValueError("MPT requires at least one prepared local clip")
        return [
            self.uv_executable,
            "run",
            "--project",
            str(self.mpt_root),
            "--frozen",
            "python",
            str(self.mpt_root / "cli.py"),
            "--task-id",
            task_id,
            "--video-script",
            script,
            "--video-source",
            "local",
            "--video-materials",
            ",".join(str(path) for path in clips),
            "--custom-audio-file",
            str(narration),
            "--video-aspect",
            "9:16",
            "--video-count",
            "1",
            "--video-concat-mode",
            "sequential",
            "--video-transition-mode",
            "none",
            "--video-clip-duration",
            str(max_clip_duration),
            "--no-subtitle-enabled",
            "--bgm-type",
            "none",
            "--stop-at",
            "video",
        ]

    def compose(
        self,
        *,
        script: str,
        narration: Path,
        clips: list[Path],
        task_id: str,
        max_clip_duration: int,
    ) -> Path:
        if not (self.mpt_root / "cli.py").exists():
            raise FileNotFoundError(f"MoneyPrinterTurbo CLI not found in {self.mpt_root}")
        result = subprocess.run(
            self.build_command(
                script=script,
                narration=narration,
                clips=clips,
                task_id=task_id,
                max_clip_duration=max_clip_duration,
            ),
            cwd=self.mpt_root,
            check=True,
            capture_output=True,
            text=True,
        )
        task_dir = self.mpt_root / "storage" / "tasks" / task_id
        resolved_task_dir = task_dir.resolve()
        for line in reversed(result.stdout.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            for candidate in _find_mp4_values(payload):
                path = Path(candidate)
                if not path.is_absolute():
                    path = self.mpt_root / path
                try:
                    path.resolve().relative_to(resolved_task_dir)
                except ValueError:
                    continue
                if path.exists():
                    return path
        matches = sorted(
            task_dir.rglob("*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True
        )
        if matches:
            return matches[0]
        raise RuntimeError("MoneyPrinterTurbo completed without reporting an output MP4")


def _find_mp4_values(value: Any) -> Iterable[str]:
    if isinstance(value, str) and value.lower().endswith(".mp4"):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _find_mp4_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _find_mp4_values(item)


class VideoEngine:
    def __init__(
        self,
        mpt: MPTAdapter,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
    ) -> None:
        self.mpt = mpt
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def render(
        self,
        *,
        run_id: str,
        run_dir: Path,
        scenes: list[Scene],
        narration: Narration,
        package: ScriptPackage,
        music: MusicTrack,
        music_volume: float = 0.08,
    ) -> tuple[Path, float]:
        if not music.local_path:
            raise ValueError("Music must be downloaded before rendering")
        prepared_dir = run_dir / "prepared-scenes"
        prepared_dir.mkdir(parents=True, exist_ok=True)
        print(f"[Render 1/4] Preparing {len(scenes)} vertical scenes...", flush=True)
        clips = []
        for index, scene in enumerate(scenes):
            print(f"[Render] Preparing scene {index + 1}/{len(scenes)}...", flush=True)
            clips.append(self._prepare_scene(scene, prepared_dir, index))
        print("[Render 2/4] MoneyPrinterTurbo is composing the base video...", flush=True)
        base = self.mpt.compose(
            script=package.script,
            narration=narration.audio_path,
            clips=clips,
            task_id=run_id,
            max_clip_duration=max(1, math.ceil(max(scene.end - scene.start for scene in scenes))),
        )
        base_copy = run_dir / "mpt-base.mp4"
        shutil.copyfile(base, base_copy)
        print("[Render 3/4] Burning karaoke subtitles, watermark, and music...", flush=True)
        ass_path = AssSubtitleEngine().write(
            run_dir / "subtitles.ass", narration, package, duration=narration.duration
        )
        final = run_dir / "final.mp4"
        ass_filter = _escape_filter_path(ass_path)
        video_filter = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,fps=30,ass='{ass_filter}'"
        )
        filter_complex = (
            f"[1:a]atrim=0:{narration.duration:.3f},asetpts=N/SR/TB,"
            f"volume=1.0[voice];[2:a]volume={music_volume},"
            f"atrim=0:{narration.duration:.3f},asetpts=N/SR/TB[bgm];"
            "[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        subprocess.run(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(base_copy),
                "-i",
                str(narration.audio_path),
                "-stream_loop",
                "-1",
                "-i",
                str(music.local_path),
                "-vf",
                video_filter,
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v:0",
                "-map",
                "[aout]",
                "-t",
                f"{narration.duration:.3f}",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(final),
            ],
            check=True,
        )
        print("[Render 4/4] Validating resolution, frame rate, audio, and duration...", flush=True)
        duration = validate_probe(probe_video(final, self.ffprobe))
        return final, duration

    def _prepare_scene(self, scene: Scene, directory: Path, index: int) -> Path:
        source = scene.asset.local_path
        if not source:
            raise ValueError(f"Scene asset {scene.asset.asset_id} is not downloaded")
        duration = max(0.1, scene.end - scene.start)
        destination = directory / f"scene-{index:02d}.mp4"
        if scene.asset.kind == "video":
            filters = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30"
            command = [
                self.ffmpeg,
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(source),
                "-t",
                f"{duration:.3f}",
                "-an",
                "-vf",
                filters,
            ]
        else:
            frames = max(1, math.ceil(duration * 30))
            filters = (
                "scale=1200:2134:force_original_aspect_ratio=increase,"
                "crop=1200:2134,"
                f"zoompan=z='min(zoom+0.00035,1.06)':x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30"
            )
            command = [
                self.ffmpeg,
                "-y",
                "-loop",
                "1",
                "-i",
                str(source),
                "-t",
                f"{duration:.3f}",
                "-an",
                "-vf",
                filters,
            ]
        command.extend(
            [
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(destination),
            ]
        )
        subprocess.run(command, check=True)
        scene.local_path = destination
        return destination


def _escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
