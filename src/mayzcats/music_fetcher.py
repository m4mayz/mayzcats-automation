from __future__ import annotations

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .models import MusicTrack

MPT_REPOSITORY = "https://github.com/harry0703/MoneyPrinterTurbo"
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
    """Select a bundled MoneyPrinterTurbo song without changing its checkout."""

    def __init__(
        self,
        mpt_root: Path,
        *,
        validator: Callable[[Path], bool] = validate_audio_file,
    ) -> None:
        self.mpt_root = Path(mpt_root)
        self.song_dir = self.mpt_root / "resource" / "songs"
        self.validator = validator

    def prepare(self, run_id: str, directory: Path) -> MusicTrack:
        candidates = sorted(
            path
            for path in self.song_dir.glob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
        )
        if not candidates:
            raise RuntimeError(
                "MoneyPrinterTurbo has no bundled music under resource/songs "
                f"({self.song_dir})"
            )

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

        source_url = f"{MPT_REPOSITORY}/blob/main/resource/songs/{selected.name}"
        return MusicTrack(
            title=selected.name,
            creator="MoneyPrinterTurbo bundled track",
            download_url=source_url,
            source_url=source_url,
            license_name="MoneyPrinterTurbo bundled music; upstream license unverified",
            license_url=f"{MPT_REPOSITORY}#background-music-",
            retrieved_at=datetime.now(UTC).isoformat(),
            local_path=destination,
            provider="moneyprinterturbo_builtin",
            sha256=selected_checksum,
            license_status="unverified_upstream",
        )
