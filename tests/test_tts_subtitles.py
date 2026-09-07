from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from mayzcats.elevenlabs_tts import ElevenLabsClient, alignment_to_words
from mayzcats.models import Narration, ScriptPackage, WordTiming
from mayzcats.subtitle_engine import AssSubtitleEngine
from mayzcats.tts_cache import PersistentTTSCache


def _timed_response(request: httpx.Request) -> httpx.Response:
    key = request.headers["xi-api-key"]
    if key == "exhausted":
        return httpx.Response(429, text="quota", request=request)
    return httpx.Response(
        200,
        json={
            "audio_base64": base64.b64encode(b"fake mp3").decode(),
            "alignment": {
                "characters": list("Hello cat"),
                "character_start_times_seconds": [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
                "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
            },
        },
        request=request,
    )


def test_tts_uses_sequential_key_fallback_and_keeps_no_secret_in_result(tmp_path: Path) -> None:
    transport = httpx.MockTransport(_timed_response)
    client = ElevenLabsClient(["exhausted", "working"], http=httpx.Client(transport=transport))

    narration = client.synthesize("Hello cat", tmp_path / "voice.mp3", probe=lambda _: 40.0)

    assert narration.key_index == 2
    assert narration.duration == 40.0
    assert [word.text for word in narration.words] == ["Hello", "cat"]
    assert (tmp_path / "voice.mp3").read_bytes() == b"fake mp3"
    assert "working" not in repr(narration)


def test_tts_does_not_rotate_keys_for_invalid_payload(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(422, text="invalid text", request=request)

    client = ElevenLabsClient(
        ["one", "two"], http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(RuntimeError, match="422"):
        client.synthesize("bad", tmp_path / "voice.mp3", probe=lambda _: 40.0)
    assert attempts == 1


def test_tts_does_not_rotate_keys_after_ambiguous_read_timeout(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("response lost after request", request=request)

    client = ElevenLabsClient(
        ["one", "two"], http=httpx.Client(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(RuntimeError, match="ambiguous"):
        client.synthesize("Do not bill this twice", tmp_path / "voice.mp3", probe=lambda _: 40.0)
    assert attempts == 1


def test_tts_rotates_keys_for_explicit_payment_or_quota_rejection(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(402, text="quota", request=request)
        return _timed_response(request)

    client = ElevenLabsClient(
        ["exhausted", "working"], http=httpx.Client(transport=httpx.MockTransport(handler))
    )

    narration = client.synthesize("Hello cat", tmp_path / "voice.mp3", probe=lambda _: 40.0)

    assert narration.key_index == 2
    assert attempts == 2


def test_persistent_tts_cache_reuses_audio_and_timings_without_new_generation(
    tmp_path: Path,
) -> None:
    class FakeClient:
        voice_id = "voice-1"
        model_id = "model-1"
        speed = 1.0
        output_format = "mp3_44100_128"

        def __init__(self) -> None:
            self.calls = 0

        def cache_identity(self) -> dict[str, object]:
            return {
                "voice_id": self.voice_id,
                "model_id": self.model_id,
                "speed": self.speed,
                "output_format": self.output_format,
                "voice_settings": {"stability": 0.5},
            }

        def synthesize(self, text: str, destination: Path) -> Narration:
            self.calls += 1
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"paid audio")
            return Narration(
                audio_path=destination,
                duration=42.5,
                words=[WordTiming("Hello", 0.0, 0.5)],
                key_index=1,
            )

    client = FakeClient()
    cache = PersistentTTSCache(tmp_path / "tts-cache")

    first = cache.get_or_create("Hello", client)
    second = cache.get_or_create("Hello", client)

    assert client.calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.audio_path.read_bytes() == b"paid audio"
    assert [(word.text, word.start, word.end) for word in second.words] == [
        ("Hello", 0.0, 0.5)
    ]


def test_alignment_to_words_uses_character_boundaries() -> None:
    words = alignment_to_words(
        {
            "characters": list("One  two"),
            "character_start_times_seconds": [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
            "character_end_times_seconds": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        }
    )
    assert [(word.text, word.start, word.end) for word in words] == [
        ("One", 0.0, 0.3),
        ("two", 0.5, 0.8),
    ]


def _script() -> ScriptPackage:
    return ScriptPackage(
        script="One two three four five six seven.",
        title="Why Cats Do This",
        description="A sourced cat fact.",
        hashtags=["#shorts", "#cats"],
        tags=["cats", "cat lovers", "pets", "cute animals"],
        hook_text="Cats do THIS for a reason",
        hook_keyword="THIS",
        search_terms=["cat behavior"],
        beats=["One two three", "four five six seven"],
        mood="playful curious",
        medical=False,
    )


def test_ass_uses_stable_karaoke_phrases_without_an_opening_hook_overlay() -> None:
    words = [
        WordTiming(word, i * 0.6, i * 0.6 + 0.3)
        for i, word in enumerate(
            ["Whisker", "fatigue", "can", "happen", "when", "deep", "bowls", "touch"]
        )
    ]
    narration = Narration(Path("voice.mp3"), 5.0, words, 1)

    ass = AssSubtitleEngine().render_text(narration, _script(), duration=5.0)

    assert "Fontname=Montserrat" in ass
    assert "WrapStyle: 0" in ass
    assert "Style: Subtitle,Montserrat,64," in ass
    assert ",2,120,120,260,1" in ass
    assert "MayzCats" in ass
    assert "Style: Hook" not in ass
    assert "Cats do" not in ass
    assert not any(line.startswith("Dialogue: 2") for line in ass.splitlines())
    subtitle_events = [line for line in ass.splitlines() if line.startswith("Dialogue: 0")]
    assert len(subtitle_events) == 2
    assert all("{\\kf" in line for line in subtitle_events)
    assert all(r"\N" in line for line in subtitle_events)

    first_fields = subtitle_events[0].split(",", 9)
    second_fields = subtitle_events[1].split(",", 9)
    assert first_fields[2] == second_fields[1]


def test_ass_phrase_fallback_uses_portrait_safe_windows_and_continuous_timing() -> None:
    package = _script()
    package.script = "Whisker fatigue can happen when deep bowls touch sensitive whiskers."
    narration = Narration(Path("voice.mp3"), 8.0, [], 1)

    ass = AssSubtitleEngine().render_text(narration, package, duration=8.0)

    subtitle_events = [line for line in ass.splitlines() if line.startswith("Dialogue: 0")]
    assert len(subtitle_events) == 3
    assert all(len(line.split(",", 9)[9].replace(r"\N", " ").split()) <= 4 for line in subtitle_events)
    assert any(r"\N" in line for line in subtitle_events)
    for current, following in zip(subtitle_events[:-1], subtitle_events[1:], strict=True):
        assert current.split(",", 9)[2] == following.split(",", 9)[1]


def test_ass_falls_back_to_phrase_timing_without_words() -> None:
    narration = Narration(Path("voice.mp3"), 7.0, [], 1)

    ass = AssSubtitleEngine().render_text(narration, _script(), duration=7.0)

    assert "One two three four" in ass
    assert "five six seven" in ass
