from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .models import MusicTrack

MPT_REPOSITORY = "https://github.com/harry0703/MoneyPrinterTurbo"
MPT_SOURCE_COMMIT = "5ceffd02a267de2ede0bbdb0fab8d7d875ea9842"
REPO_MUSIC_DIR = Path(__file__).resolve().parents[1] / "music"
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_audio_file(path: Path, ffprobe: str = "ffprobe") -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
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
        return float(result.stdout.strip()) > 0
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


class MPTMusicLibrary:
    """Select a vendored MoneyPrinterTurbo song from this repository."""

    def __init__(
        self,
        song_dir: Path = REPO_MUSIC_DIR,
        *,
        excluded_files: set[str] | None = None,
        validator: Callable[[Path], bool] = validate_audio_file,
    ) -> None:
        self.song_dir = Path(song_dir)
        self.excluded_files = excluded_files or set()
        self.validator = validator

    def prepare(self, run_id: str, directory: Path) -> MusicTrack:
        candidates = sorted(
            path
            for path in self.song_dir.glob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
            and path.name not in self.excluded_files
        )
        if not candidates:
            raise RuntimeError(f"MayzCats has no selectable bundled music in {self.song_dir}")

        start = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest(), 16) % len(candidates)
        ordered = candidates[start:] + candidates[:start]
        selected = next((path for path in ordered if self.validator(path)), None)
        if selected is None:
            raise RuntimeError(
                f"No readable MoneyPrinterTurbo music file found in {self.song_dir}"
            )

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / selected.name
        selected_checksum = _sha256(selected)
        if not destination.exists() or _sha256(destination) != selected_checksum:
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copyfile(selected, temporary)
            temporary.replace(destination)

        source_url = (
            f"{MPT_REPOSITORY}/blob/{MPT_SOURCE_COMMIT}/resource/songs/{selected.name}"
        )
        return MusicTrack(
            title=selected.name,
            creator="MoneyPrinterTurbo bundled track",
            download_url=source_url,
            source_url=source_url,
            license_name="MoneyPrinterTurbo bundled music; upstream license unverified",
            license_url=f"{MPT_REPOSITORY}/blob/{MPT_SOURCE_COMMIT}/README-en.md#background-music",
            retrieved_at=datetime.now(UTC).isoformat(),
            local_path=destination,
            provider="moneyprinterturbo_builtin",
            sha256=selected_checksum,
            license_status="unverified_upstream",
        )
