"""GitHub-only runtime adapter. Keeps credentials out of Git and artifacts."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
STATE = ROOT / "state"
SCHEDULE = STATE / "actions.json"
PERIOD = 5 * 60 * 60


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def due(schedule, now, force=False):
    return force or int(now // PERIOD) > schedule.get("last_slot", -1)


def gate(force=False):
    schedule = read_json(SCHEDULE, {})
    ready = due(schedule, time.time(), force)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"due={str(ready).lower()}\n")
        output.write(f"snapshot={schedule.get('snapshot_run_id', '')}\n")


def prepare():
    import yaml

    from mayzcats.config import required_secrets
    from mayzcats.storage import DriveLayout

    config = yaml.safe_load((ROOT / "config/pipeline.yaml").read_text(encoding="utf-8"))
    missing = [key for key in (*required_secrets(config), "YOUTUBE_CLIENT_SECRET_JSON", "YOUTUBE_TOKEN_JSON")
               if not os.environ.get(key, "").strip()]
    if missing:
        raise ValueError("Missing GitHub Secrets: " + ", ".join(missing))
    # Validate without ever printing JSON credentials or exception bodies.
    documents = {}
    try:
        for key in ("YOUTUBE_CLIENT_SECRET_JSON", "YOUTUBE_TOKEN_JSON"):
            documents[key] = json.loads(os.environ[key])
        if not documents["YOUTUBE_TOKEN_JSON"].get("refresh_token"):
            raise ValueError("Missing refresh token")
    except (ValueError, AttributeError):
        raise ValueError("Invalid YouTube JSON secrets; token must include a refresh_token") from None
    layout = DriveLayout.bootstrap(RUNTIME, ROOT / "config")
    for name in ("channel.yaml", "pipeline.yaml"):
        shutil.copyfile(ROOT / "config" / name, layout.config_dir / name)
    shutil.copyfile(STATE / "topic_history.json", layout.topic_history)
    shutil.copyfile(STATE / "runs.jsonl", layout.runs_log)
    write_json(layout.client_secret, documents["YOUTUBE_CLIENT_SECRET_JSON"])
    write_json(layout.token_file, documents["YOUTUBE_TOKEN_JSON"])
    # Record only after successful preparation; failed installation must not consume a slot.
    write_json(RUNTIME / "attempt.json", {"slot": int(time.time() // PERIOD)})


def run(mode):
    from mayzcats.youtube_upload import load_credentials

    def no_interactive_login(_prompt):
        raise RuntimeError("Update YOUTUBE_TOKEN_JSON with an authorized refresh token")

    try:
        load_credentials(
            RUNTIME / "secrets/youtube/client_secret.json",
            RUNTIME / "secrets/youtube/token.json",
            input_fn=no_interactive_login, print_fn=lambda _message: None,
        )
    except Exception:
        print("YouTube authorization failed; renew YOUTUBE_TOKEN_JSON.", file=sys.stderr)
        return 1
    mpt = ROOT / "vendor/MoneyPrinterTurbo"
    check = subprocess.run([sys.executable, "-m", "mayzcats.preflight",
                            "--drive-root", str(RUNTIME), "--mpt-root", str(mpt)])
    if check.returncode:
        return check.returncode
    command = [sys.executable, "-u", "-m", "mayzcats.pipeline",
               "--drive-root", str(RUNTIME), "--mpt-root", str(mpt),
               "--work-root", str(ROOT / ".render")]
    pending = read_json(SCHEDULE, {}).get("pending_run")
    if pending and mode == "auto":
        checkpoint_dir = RUNTIME / "runs" / pending
        checkpoint = read_json(checkpoint_dir / "state.json", {})
        if "Duplicate topic blocked:" in str(checkpoint.get("error", "")):
            print(f"[Recovery] Abandoning duplicate topic checkpoint {pending}; starting a new run.")
            shutil.rmtree(checkpoint_dir)
            pending = None
    attempt = read_json(RUNTIME / "attempt.json", {})
    attempt["prior_checkpoints"] = [path.name for path in (RUNTIME / "runs").iterdir()]
    attempt["resume_id"] = pending if mode == "auto" else None
    write_json(RUNTIME / "attempt.json", attempt)
    if pending and mode == "auto":
        if not (RUNTIME / "runs" / pending / "state.json").is_file():
            raise RuntimeError("Pending checkpoint missing; restore artifact or explicitly select new mode")
        command.extend(["--resume", pending])
    return subprocess.run(command).returncode


def persist():
    attempt = read_json(RUNTIME / "attempt.json", None)
    if attempt is None:
        return
    history = read_json(RUNTIME / "state/topic_history.json", [])
    # Public Git state contains only publication identity, not source bodies or local paths.
    compact = []
    for entry in history:
        metadata = entry.get("metadata", {})
        compact.append({**{k: entry[k] for k in (
            "subject", "angle", "published_at", "youtube_video_id")},
            "metadata": {k: metadata[k] for k in ("title", "run_id", "privacy") if k in metadata}})
    write_json(STATE / "topic_history.json", compact)
    source = RUNTIME / "state/runs.jsonl"
    records = []
    fields = ("run_id", "status", "topic", "angle", "youtube_video_id", "uploaded_at", "privacy")
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            records.append({k: entry[k] for k in fields if k in entry})
    (STATE / "runs.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    published = {entry["metadata"].get("run_id") for entry in compact}
    checkpoints = []
    for path in (RUNTIME / "runs").glob("*/state.json"):
        entry = read_json(path, {})
        belongs_to_attempt = (path.parent.name == attempt.get("resume_id")
                              or path.parent.name not in attempt.get("prior_checkpoints", []))
        if belongs_to_attempt and entry.get("run_id") not in published:
            checkpoints.append((entry.get("updated_at", ""), path.parent.name))
    pending = max(checkpoints)[1] if checkpoints else None
    write_json(SCHEDULE, {
        "last_slot": attempt["slot"],
        "snapshot_run_id": os.environ["GITHUB_RUN_ID"],
        "pending_run": pending,
    })
    write_json(RUNTIME / "snapshot.json", {"github_run_id": os.environ["GITHUB_RUN_ID"]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("gate", "prepare", "run", "persist"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--mode", choices=("auto", "new"), default="auto")
    args = parser.parse_args()
    if args.command == "gate":
        gate(args.force)
    elif args.command == "prepare":
        prepare()
    elif args.command == "persist":
        persist()
    else:
        raise SystemExit(run(args.mode))
