from __future__ import annotations

import base64
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .models import Narration, WordTiming

VOICE_ID = "cgSgspJ2msm6clMCkdW9"
MODEL_ID = "eleven_multilingual_v2"
RETRYABLE_STATUSES = {401, 402, 403, 408, 409, 429, 500, 502, 503, 504}


def alignment_to_words(alignment: dict[str, Any] | None) -> list[WordTiming]:
    if not alignment:
        return []
    characters = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not (len(characters) == len(starts) == len(ends)):
        return []
    words: list[WordTiming] = []
    current: list[str] = []
    word_start = 0.0
    word_end = 0.0
    for character, start, end in zip(characters, starts, ends, strict=True):
        character = str(character)
        if character.isspace():
            if current:
                words.append(WordTiming("".join(current), word_start, word_end))
                current = []
            continue
        if not current:
            word_start = float(start)
        current.append(character)
        word_end = float(end)
    if current:
        words.append(WordTiming("".join(current), word_start, word_end))
    return words


def probe_audio_duration(path: Path, ffprobe: str = "ffprobe") -> float:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


class ElevenLabsClient:
    def __init__(
        self,
        api_keys: list[str],
        *,
        voice_id: str = VOICE_ID,
        model_id: str = MODEL_ID,
        speed: float = 1.08,
        output_format: str = "mp3_44100_128",
        http: httpx.Client | None = None,
    ) -> None:
        self.api_keys = [key for key in api_keys if key.strip()]
        if not self.api_keys:
            raise ValueError("At least one ElevenLabs API key is required")
        self.voice_id = voice_id
        self.model_id = model_id
        self.speed = speed
        self.output_format = output_format
        self.http = http or httpx.Client(timeout=180.0)
        self._preferred_key_index = 0

    def cache_identity(self) -> dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "speed": self.speed,
            "output_format": self.output_format,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

    def synthesize(
        self,
        text: str,
        destination: Path,
        *,
        probe: Callable[[Path], float] = probe_audio_duration,
    ) -> Narration:
        if not text.strip():
            raise ValueError("TTS text cannot be empty")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/with-timestamps"
        identity = self.cache_identity()
        body = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                **identity["voice_settings"],
                "speed": self.speed,
            },
        }
        failures: list[str] = []
        order = list(range(self._preferred_key_index, len(self.api_keys))) + list(
            range(0, self._preferred_key_index)
        )
        for key_index in order:
            try:
                response = self.http.post(
                    endpoint,
                    params={"output_format": self.output_format},
                    headers={
                        "xi-api-key": self.api_keys[key_index],
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            except (httpx.ReadTimeout, httpx.ReadError) as exc:
                raise RuntimeError(
                    "ElevenLabs TTS result is ambiguous after the request"
                    " response was interrupted; automatic key rotation was stopped to avoid duplicate billing"
                ) from exc
            except httpx.RequestError as exc:
                failures.append(type(exc).__name__)
                continue
            if response.status_code >= 400:
                if response.status_code not in RETRYABLE_STATUSES:
                    raise RuntimeError(f"ElevenLabs TTS failed with HTTP {response.status_code}")
                failures.append(f"HTTP {response.status_code}")
                continue
            data = response.json()
            encoded = data.get("audio_base64")
            if not isinstance(encoded, str) or not encoded:
                raise RuntimeError("ElevenLabs timing response did not include audio_base64")
            try:
                audio = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise RuntimeError("ElevenLabs returned invalid base64 audio") from exc
            destination.write_bytes(audio)
            alignment = data.get("normalized_alignment") or data.get("alignment")
            words = alignment_to_words(alignment)
            self._preferred_key_index = key_index
            return Narration(
                audio_path=destination,
                duration=probe(destination),
                words=words,
                key_index=key_index + 1,
            )
        summary = ", ".join(failures) or "unknown errors"
        raise RuntimeError(f"All ElevenLabs API keys failed sequentially: {summary}")
