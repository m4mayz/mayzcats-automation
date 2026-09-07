from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import REQUIRED_SECRETS, Settings
from .storage import DriveLayout


def check_environment(
    drive_root: Path,
    mpt_root: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    project_root = project_root or Path(__file__).resolve().parents[2]
    layout = DriveLayout.bootstrap(drive_root, project_root / "config")
    settings = Settings.load(layout, mpt_root=mpt_root)
    checks: dict[str, Any] = {
        "drive_root": layout.root.is_dir(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "uv": shutil.which("uv") is not None,
        "mpt_cli": (mpt_root / "cli.py").is_file(),
        "mpt_music": any(
            path.is_file()
            for path in (mpt_root / "resource" / "songs").glob("*.mp3")
        ),
        "youtube_client_secret": layout.client_secret.is_file(),
    }
    missing_secrets = [
        name for name in REQUIRED_SECRETS if not settings.secrets.get(name, "").strip()
    ]
    checks["required_secrets"] = not missing_secrets
    checks["missing_secrets"] = missing_secrets
    font_ok = False
    if checks["ffmpeg"] and shutil.which("fc-match"):
        result = subprocess.run(
            ["fc-match", "Montserrat"], capture_output=True, text=True, check=False
        )
        font_ok = result.returncode == 0 and "montserrat" in result.stdout.lower()
    checks["montserrat"] = font_ok
    checks["ok"] = all(
        bool(checks[name])
        for name in (
            "drive_root",
            "ffmpeg",
            "ffprobe",
            "uv",
            "mpt_cli",
            "mpt_music",
            "youtube_client_secret",
            "required_secrets",
            "montserrat",
        )
    )
    return checks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate MayzCats Colab prerequisites")
    parser.add_argument(
        "--drive-root",
        type=Path,
        default=Path("/content/drive/MyDrive/MayzCats-Automation"),
    )
    parser.add_argument(
        "--mpt-root", type=Path, default=Path("/content/mayzcats/MoneyPrinterTurbo")
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = check_environment(args.drive_root, args.mpt_root)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
