# Main Branch Runtime Design

## Goal

Make `main` the single source of truth for MayzCats. GitHub Actions is the only
runtime; the Google Colab runtime is retired and its code, naming, and
documentation are removed.

Approved by Akmal on 2026-09-29 (merge approach, full Colab cleanup).

## Current State

- `codex/github-actions` holds the code that actually runs, plus
  `.github/workflows/github-runner.yml`, `config/`, and `state/`.
- `main` holds an older Colab-era copy of `src/` (76 commits behind) and
  `.github/workflows/mayzcats-schedule.yml`, a dispatcher that calls
  `github-runner.yml@codex/github-actions`. Its 4 main-only commits touch only
  that dispatcher.
- The runtime checks out `codex/github-actions` and the state step pushes bot
  commits there.

## Branch Migration

Merge `codex/github-actions` into `main` with a normal merge commit. No history
rewrite and no force push. `main` has no branch protection or rulesets.

After the merge, `main` contains one workflow, `github-runner.yml`:

- Triggers: `schedule` with crons `0 0 * * *` and `0 7 * * *` (07:00 and
  14:00 WIB), and `workflow_dispatch` with the existing `force` and `mode`
  inputs. `workflow_call` is removed.
- Publish hour: `16` for the `0 0 * * *` event, `23` for `0 7 * * *`, empty for
  manual dispatch (immediate upload). Same mapping the dispatcher uses today.
- Checkout uses the triggering ref (`main`); the hard-coded
  `ref: codex/github-actions` is removed.
- The state step rebases on and pushes to `main`.

Removed: `.github/workflows/mayzcats-schedule.yml` and
`docs/github-actions-dispatcher.yml`.

Unchanged: Actions artifacts, `state/actions.json` format, the `.runtime/`
directory layout, and the concurrency group. The current `pending_run` checkpoint
and its snapshot artifact remain resumable because artifact download is by run
ID, not branch.

Bot state commits on `main` also keep the default branch active, which prevents
GitHub from disabling the schedule after 60 days of inactivity.

After the first successful scheduled run from `main`, delete the remote
`codex/github-actions` branch.

## Colab Cleanup

Delete:

- `MayzCats_V1_Colab.ipynb`
- `scripts/verify_notebook.py`
- `tests/test_notebook_contract.py`

Rename:

- `src/mayzcats/colab_bootstrap.py` to `src/mayzcats/system_deps.py`, and
  `tests/test_colab_bootstrap.py` to `tests/test_system_deps.py`.
- `DriveLayout` to `RuntimeLayout`.
- `--drive-root` / `drive_root` to `--runtime-root` / `runtime_root` in the
  pipeline and preflight CLIs, `build_settings`, `retry_failed_upload`,
  `check_environment`, and `scripts/github_runner.py`.

Remove the `/content/...` defaults. `--runtime-root` and `--mpt-root` become
required CLI arguments; `Settings` no longer defaults `work_root` or `mpt_root`
to Colab paths. The runner already passes both.

Reword Drive/Colab wording in log messages, the `pyproject.toml` description, and
the preflight CLI description.

Rewrite `README.md` for the Actions runtime and fold `docs/github-actions.md`
into it, then delete `docs/github-actions.md` so setup lives in one place.

Kept: `.env.example` and `secrets/.env` loading (local runs), the `.runtime/`
directory name, and existing specs and plans under `docs/superpowers/` as
historical records.

## Verification

- `pytest -q` and `ruff check .` pass on the final tree.
- `actionlint` on `github-runner.yml` if available locally; otherwise reported as
  not run.
- `git grep -i -e colab -e drive` over `src`, `scripts`, `tests`, `.github`,
  `config`, `pyproject.toml`, and `README.md` returns no stale references.
- First live verification is the next scheduled run from `main` (07:00 WIB).
  No manual dispatch, because it would upload a real video immediately.

## Rollback

If the first scheduled run from `main` fails for a workflow reason, restore
`mayzcats-schedule.yml` on `main` pointing at `codex/github-actions` (kept until
that run succeeds) and remove the schedule trigger from `github-runner.yml` on
`main`.
