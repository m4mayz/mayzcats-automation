from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mayzcats.media_fetcher import (
    normalize_pexels_videos,
    normalize_pixabay_videos,
    select_assets,
)
from mayzcats.models import MediaAsset, MusicTrack, Narration, Scene, ScriptPackage
from mayzcats.music_fetcher import MPTMusicLibrary
from mayzcats.scene_planner import plan_scenes
from mayzcats.video_engine import MPTAdapter, VideoEngine, validate_probe


def _asset(asset_id: str, kind: str = "video", score: float = 1.0) -> MediaAsset:
    return MediaAsset(
        asset_id=asset_id,
        provider="test",
        kind=kind,
        download_url=f"https://cdn.example/{asset_id}",
        source_url=f"https://example/{asset_id}",
        creator="Creator",
        license_name="Test License",
        license_url="https://example/license",
        width=1080,
        height=1920,
        duration=10.0 if kind == "video" else None,
        score=score,
    )


def test_media_normalizers_keep_source_and_license_trace() -> None:
    pexels = normalize_pexels_videos(
        {
            "videos": [
                {
                    "id": 1,
                    "url": "https://pexels.com/video/1",
                    "duration": 9,
                    "user": {"name": "A"},
                    "video_files": [
                        {
                            "link": "https://cdn/1.mp4",
                            "width": 1080,
                            "height": 1920,
                            "quality": "hd",
                        }
                    ],
                }
            ]
        }
    )
    pixabay = normalize_pixabay_videos(
        {
            "hits": [
                {
                    "id": 2,
                    "pageURL": "https://pixabay.com/videos/2",
                    "duration": 8,
                    "user": "B",
                    "videos": {
                        "medium": {
                            "url": "https://cdn/2.mp4",
                            "width": 1920,
                            "height": 1080,
                            "size": 10,
                        }
                    },
                }
            ]
        }
    )

    assert pexels[0].license_url == "https://www.pexels.com/license/"
    assert pexels[0].source_url == "https://pexels.com/video/1"
    assert pixabay[0].license_url == "https://pixabay.com/service/terms/"
    assert pixabay[0].creator == "B"


def test_asset_selection_prefers_video_and_uses_every_unique_asset_before_reuse() -> None:
    assets = [_asset("image", "image", 9), _asset("v1", "video", 2), _asset("v2", "video", 1)]

    selected = select_assets(assets, count=4)

    assert [item.asset_id for item in selected[:3]] == ["v1", "v2", "image"]
    assert selected[3].asset_id == "v1"


def test_scene_planner_is_adaptive_and_covers_narration_exactly() -> None:
    scenes = plan_scenes(
        duration=12.0,
        beats=["short", "this beat has many more important words than the others", "medium beat"],
        assets=[_asset("a"), _asset("b"), _asset("c")],
    )

    durations = [round(scene.end - scene.start, 2) for scene in scenes]
    assert scenes[0].start == 0
    assert scenes[-1].end == 12.0
    assert len(set(durations)) > 1
    assert 1.0 <= durations[0] <= 2.0


def test_scene_planner_interleaves_other_clips_before_reusing_a_short_video() -> None:
    assets = [_asset("a"), _asset("b"), _asset("c")]
    for asset in assets:
        asset.duration = 2.0

    scenes = plan_scenes(duration=8.0, beats=["one long beat"], assets=assets)
    ids = [scene.asset.asset_id for scene in scenes]

    assert ids == ["a", "b", "c", "a"]
    assert all(left != right for left, right in zip(ids, ids[1:], strict=False))
    assert scenes[-1].end == 8.0


def test_mpt_music_library_copies_a_bundled_track_with_source_trace(tmp_path: Path) -> None:
    songs = tmp_path / "music"
    songs.mkdir(parents=True)
    (songs / "output000.mp3").write_bytes(b"first")
    (songs / "output001.mp3").write_bytes(b"second")

    track = MPTMusicLibrary(songs, validator=lambda _: True).prepare(
        "run-123", tmp_path / "checkpoint-music"
    )

    assert track.local_path is not None
    assert track.local_path.parent == tmp_path / "checkpoint-music"
    assert track.local_path.read_bytes() in {b"first", b"second"}
    assert track.provider == "moneyprinterturbo_builtin"
    assert track.source_url.endswith(f"/resource/songs/{track.title}")
    assert track.license_status == "unverified_upstream"
    assert len(track.sha256) == 64


def test_mpt_music_library_skips_excluded_tracks(tmp_path: Path) -> None:
    songs = tmp_path / "music"
    songs.mkdir()
    (songs / "output000.mp3").write_bytes(b"excluded")
    (songs / "output001.mp3").write_bytes(b"allowed")

    track = MPTMusicLibrary(
        songs,
        excluded_files={"output000.mp3"},
        validator=lambda _: True,
    ).prepare("run-123", tmp_path / "checkpoint-music")

    assert track.title == "output001.mp3"
    assert track.local_path is not None
    assert track.local_path.read_bytes() == b"allowed"


def test_mpt_music_library_fails_before_tts_when_repo_has_no_selectable_songs(
    tmp_path: Path,
) -> None:
    songs = tmp_path / "music"
    songs.mkdir()
    (songs / "output000.mp3").write_bytes(b"excluded")

    with pytest.raises(RuntimeError, match="selectable bundled music"):
        MPTMusicLibrary(songs, excluded_files={"output000.mp3"}).prepare(
            "run-123", tmp_path / "checkpoint-music"
        )


def test_mpt_command_uses_local_prepared_assets_and_disables_mpt_overlays(tmp_path: Path) -> None:
    adapter = MPTAdapter(tmp_path / "MoneyPrinterTurbo", uv_executable="uv")
    command = adapter.build_command(
        script="A safe cat script",
        narration=tmp_path / "voice.mp3",
        clips=[tmp_path / "1.mp4", tmp_path / "2.mp4"],
        task_id="123e4567-e89b-12d3-a456-426614174000",
        max_clip_duration=6,
    )

    joined = " ".join(command)
    assert "--video-source local" in joined
    assert "--custom-audio-file" in joined
    assert "--no-subtitle-enabled" in joined
    assert "--bgm-type none" in joined
    assert "--video-concat-mode sequential" in joined
    assert "--video-aspect 9:16" in joined


def test_mpt_result_ignores_existing_input_mp4_outside_task_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mpt_root = tmp_path / "MoneyPrinterTurbo"
    mpt_root.mkdir()
    (mpt_root / "cli.py").write_text("# test CLI\n", encoding="utf-8")
    task_id = "123e4567-e89b-12d3-a456-426614174000"
    output = mpt_root / "storage" / "tasks" / task_id / "final-1.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"output")
    input_clip = tmp_path / "prepared-input.mp4"
    input_clip.write_bytes(b"input")

    monkeypatch.setattr(
        "mayzcats.video_engine.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=json.dumps({"result": {"materials": [str(input_clip)], "videos": [str(output)]}})
        ),
    )

    result = MPTAdapter(mpt_root).compose(
        script="Script",
        narration=tmp_path / "voice.mp3",
        clips=[input_clip],
        task_id=task_id,
        max_clip_duration=6,
    )

    assert result == output


def test_probe_validation_requires_exact_vertical_30fps_and_audio() -> None:
    valid = {
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "r_frame_rate": "30/1"},
            {"codec_type": "audio"},
        ],
        "format": {"duration": "43.2"},
    }
    assert validate_probe(valid) == pytest.approx(43.2)
    invalid = {
        **valid,
        "streams": [{"codec_type": "video", "width": 720, "height": 1280, "r_frame_rate": "30/1"}],
    }
    with pytest.raises(ValueError, match="1080x1920"):
        validate_probe(invalid)


def test_final_render_uses_the_original_narration_for_the_complete_voice_track(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "mpt-base.mp4"
    base.write_bytes(b"base")
    narration = tmp_path / "elevenlabs-narration.mp3"
    narration.write_bytes(b"complete voice")
    music = tmp_path / "music.mp3"
    music.write_bytes(b"music")
    prepared = tmp_path / "prepared.mp4"
    prepared.write_bytes(b"prepared")
    asset = _asset("cat")
    asset.local_path = prepared

    class FakeMPT:
        def compose(self, **kwargs):
            return base

    commands: list[list[str]] = []
    monkeypatch.setattr(
        "mayzcats.video_engine.subprocess.run",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        "mayzcats.video_engine.probe_video",
        lambda path, ffprobe: {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1080,
                    "height": 1920,
                    "r_frame_rate": "30/1",
                },
                {"codec_type": "audio"},
            ],
            "format": {"duration": "40.0"},
        },
    )
    engine = VideoEngine(FakeMPT(), ffmpeg="ffmpeg", ffprobe="ffprobe")
    monkeypatch.setattr(engine, "_prepare_scene", lambda scene, directory, index: prepared)

    engine.render(
        run_id="run-1",
        run_dir=tmp_path / "run",
        scenes=[Scene(asset=asset, start=0.0, end=40.0, beat_index=0)],
        narration=Narration(narration, 40.0, [], 1),
        package=ScriptPackage(
            script="Cats have sensitive whiskers.",
            title="Cat Whiskers",
            description="Description",
            hashtags=["#shorts", "#cats"],
            tags=["cats"],
            hook_text="Unused hook",
            hook_keyword="hook",
            search_terms=["cat whiskers"],
            beats=["cat eating"],
            mood="warm",
            medical=False,
        ),
        music=MusicTrack(
            title="music.mp3",
            creator="MPT",
            download_url="https://example.test/music.mp3",
            source_url="https://example.test/music.mp3",
            license_name="upstream",
            license_url="https://example.test/license",
            retrieved_at="now",
            local_path=music,
        ),
    )

    command = commands[-1]

    assert command[:10] == [
        "ffmpeg",
        "-y",
        "-i",
        str(tmp_path / "run" / "mpt-base.mp4"),
        "-i",
        str(narration),
        "-stream_loop",
        "-1",
        "-i",
        str(music),
    ]
    audio_filter = command[command.index("-filter_complex") + 1]
    assert "[1:a]atrim=0:40.000" in audio_filter
    assert "[2:a]volume=0.08" in audio_filter
    assert "[0:a]" not in audio_filter
