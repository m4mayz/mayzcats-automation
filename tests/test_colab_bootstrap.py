from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mayzcats.colab_bootstrap import MONTSERRAT_URL, ensure_system_dependencies


def test_colab_bootstrap_installs_ffmpeg_separately_and_downloads_montserrat(
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    downloaded = False

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        commands.append(command)
        if command[0] == "fc-match":
            family = "Montserrat" if downloaded else "DejaVu Sans"
            return SimpleNamespace(stdout=family)
        return SimpleNamespace(stdout="")

    def fake_download(url: str, destination: Path) -> None:
        nonlocal downloaded
        assert url == MONTSERRAT_URL
        destination.write_bytes(b"\x00\x01\x00\x00" + (b"font" * 40_000))
        downloaded = True

    ensure_system_dependencies(
        font_dir=tmp_path,
        run=fake_run,
        download=fake_download,
        which=lambda name: None if name == "ffmpeg" else f"/usr/bin/{name}",
    )

    assert ["apt-get", "install", "-y", "ffmpeg"] in commands
    assert all("fonts-montserrat" not in command for command in commands)
    assert (tmp_path / "Montserrat-VariableFont_wght.ttf").is_file()
    assert commands[-1][0] == "fc-match"
