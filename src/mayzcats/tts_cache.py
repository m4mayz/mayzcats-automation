from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .models import Narration, WordTiming


class TTSClient(Protocol):
    def cache_identity(self) -> dict[str, object]: ...

    def synthesize(self, text: str, destination: Path) -> Narration: ...


class PersistentTTSCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def key_for(self, text: str, client: TTSClient) -> str:
        payload = {"text": text, **client.cache_identity()}
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get_or_create(self, text: str, client: TTSClient) -> Narration:
        key = self.key_for(text, client)
        cache_dir = self.root / key
        cached = self._load(cache_dir)
        if cached is not None:
            cached.cache_hit = True
            return cached

        temporary = self.root / f".{key}.{uuid4().hex}.tmp"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            narration = client.synthesize(text, temporary / "narration.mp3")
            if narration.duration <= 0 or not narration.audio_path.is_file():
                raise RuntimeError("ElevenLabs returned an invalid narration for caching")
            manifest = {
                "cache_key": key,
                "duration": narration.duration,
                "key_index": narration.key_index,
                "words": [
                    {"text": word.text, "start": word.start, "end": word.end}
                    for word in narration.words
                ],
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if cache_dir.exists():
                cached = self._load(cache_dir)
                if cached is not None:
                    return cached
                shutil.rmtree(cache_dir)
            temporary.replace(cache_dir)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

        created = self._load(cache_dir)
        if created is None:
            raise RuntimeError("TTS cache commit did not produce a readable entry")
        return created

    @staticmethod
    def _load(cache_dir: Path) -> Narration | None:
        audio_path = cache_dir / "narration.mp3"
        manifest_path = cache_dir / "manifest.json"
        if not audio_path.is_file() or audio_path.stat().st_size <= 0 or not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            duration = float(data["duration"])
            if duration <= 0:
                return None
            words = [
                WordTiming(
                    text=str(item["text"]),
                    start=float(item["start"]),
                    end=float(item["end"]),
                )
                for item in data.get("words", [])
            ]
            return Narration(
                audio_path=audio_path,
                duration=duration,
                words=words,
                key_index=int(data.get("key_index", 0)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
