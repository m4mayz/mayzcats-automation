# GitHub Source of Truth Design

## Goal

Make the public `m4mayz/mayzcats-automation` GitHub repository the canonical
source for MayzCats code while keeping persistent and private runtime data in
Google Drive.

## Ownership

GitHub contains the Python package, tests, example configuration, documentation,
scripts, and the canonical Colab notebook. Google Drive may contain a copy of
the notebook for convenient launching, but that copy is not the source of truth.

Google Drive retains only runtime-owned data: `.env`, YouTube OAuth credentials
and tokens, editable runtime configuration, state, caches, downloaded media,
checkpoints, logs, failed-upload packages, and rendered output.

## Colab Bootstrap

On every fresh Colab runtime, the notebook mounts Drive and shallow-clones
`https://github.com/m4mayz/mayzcats-automation.git` into
`/content/mayzcats-project`. It never copies source from
`MyDrive/MayzCats-Automation/project` and no longer supports the Drive ZIP
bootstrap path.

The existing `DriveLayout.bootstrap` flow continues to create persistent Drive
directories and copy example configuration only when the corresponding runtime
files do not already exist. MoneyPrinterTurbo remains a separate checkout under
`/content/mayzcats/MoneyPrinterTurbo`.

## Public Repository Safety

The repository must exclude environment files, credentials, OAuth tokens,
runtime configuration, caches, media, logs, state, checkpoints, build output,
and notebook execution output. The initial commit is scanned for common secret
patterns before the repository is pushed.

## Verification

The notebook contract test must require the GitHub clone URL and reject the old
Drive project-copy path. The full offline test suite, Ruff, notebook verifier,
compile check, package build, and a staged-file secret scan must pass before the
public push. Live API calls and YouTube uploads remain outside local verification.
