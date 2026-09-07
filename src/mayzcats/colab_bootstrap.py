from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.request import urlopen

MONTSERRAT_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf"
)
FONT_FILENAME = "Montserrat-VariableFont_wght.ttf"


def _download(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".download")
    try:
        with urlopen(url, timeout=60) as response, temporary.open("wb") as output:  # noqa: S310
            shutil.copyfileobj(response, output)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_font(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 100_000:
        raise RuntimeError(f"Downloaded Montserrat font is missing or incomplete: {path}")
    with path.open("rb") as font:
        if font.read(4) not in {b"\x00\x01\x00\x00", b"OTTO"}:
            raise RuntimeError(f"Downloaded Montserrat file is not a valid OpenType font: {path}")


def ensure_system_dependencies(
    *,
    font_dir: Path = Path("/usr/local/share/fonts/truetype/montserrat"),
    run: Callable[..., Any] = subprocess.run,
    download: Callable[[str, Path], None] = _download,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    packages: list[str] = []
    if which("ffmpeg") is None:
        packages.append("ffmpeg")
    if which("fc-match") is None:
        packages.append("fontconfig")
    if packages:
        run(["apt-get", "update"], check=True)
        run(["apt-get", "install", "-y", *packages], check=True)

    match = run(
        ["fc-match", "-f", "%{family}", "Montserrat"],
        check=True,
        capture_output=True,
        text=True,
    )
    if "montserrat" not in match.stdout.lower():
        font_dir.mkdir(parents=True, exist_ok=True)
        font_path = font_dir / FONT_FILENAME
        if not font_path.exists():
            download(MONTSERRAT_URL, font_path)
        _validate_font(font_path)
        run(["fc-cache", "-f"], check=True)

    verified = run(
        ["fc-match", "-f", "%{family}", "Montserrat"],
        check=True,
        capture_output=True,
        text=True,
    )
    if "montserrat" not in verified.stdout.lower():
        raise RuntimeError("Montserrat was installed but fontconfig cannot resolve it")
