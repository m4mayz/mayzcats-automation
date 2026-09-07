# GitHub Source of Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish MayzCats as a public GitHub repository and make Colab clone its source while Drive stores only persistent runtime data.

**Architecture:** The canonical package and notebook live in `m4mayz/mayzcats-automation`. A fresh Colab runtime shallow-clones that repository into `/content/mayzcats-project`, then the existing `DriveLayout` initializes private configuration, credentials, state, caches, and output below `MyDrive/MayzCats-Automation`.

**Tech Stack:** Git, GitHub, Python 3.11, pytest, Jupyter Notebook, Google Colab

**Spec:** `docs/superpowers/specs/2026-09-07-github-source-of-truth-design.md`

## Global Constraints

- The GitHub repository is public and named `m4mayz/mayzcats-automation`.
- Google Drive must not contain or provide the package source checkout.
- The canonical notebook stays versioned in GitHub; Drive may hold a launch copy.
- Secrets, OAuth files, runtime config, cache, state, media, logs, checkpoints, and output must not be committed.
- No live paid API or YouTube upload is part of local verification.

---

### Task 1: Make Colab clone the canonical repository

**Files:**
- Modify: `tests/test_notebook_contract.py`
- Modify: `MayzCats_V1_Colab.ipynb`

**Interfaces:**
- Consumes: public Git URL `https://github.com/m4mayz/mayzcats-automation.git`
- Produces: a fresh checkout at `/content/mayzcats-project`

- [ ] **Step 1: Write the failing notebook contract assertions**

```python
assert "https://github.com/m4mayz/mayzcats-automation.git" in code
assert "PROJECT_SOURCE" not in code
assert "DRIVE_ROOT / 'project'" not in code
assert all(cell.get("execution_count") is None for cell in notebook["cells"] if cell.get("cell_type") == "code")
assert all(not cell.get("outputs") for cell in notebook["cells"] if cell.get("cell_type") == "code")
```

- [ ] **Step 2: Run the contract test and confirm the old Drive-copy flow fails it**

Run: `python -m pytest tests/test_notebook_contract.py -q`

Expected: FAIL because the GitHub URL is absent and `PROJECT_SOURCE` is present.

- [ ] **Step 3: Replace the notebook's source staging branch with one shallow clone**

```python
PROJECT_URL = 'https://github.com/m4mayz/mayzcats-automation.git'
RUNTIME_PROJECT = Path('/content/mayzcats-project')
if RUNTIME_PROJECT.exists():
    shutil.rmtree(RUNTIME_PROJECT)
subprocess.run(['git', 'clone', '--depth', '1', PROJECT_URL, str(RUNTIME_PROJECT)], check=True)
```

- [ ] **Step 4: Run the contract test**

Run: `python -m pytest tests/test_notebook_contract.py -q`

Expected: PASS.

### Task 2: Document and enforce the public/private boundary

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: repository checkout and `MyDrive/MayzCats-Automation`
- Produces: explicit setup instructions and Git exclusions for private/runtime data

- [ ] **Step 1: Ignore runtime-owned paths and common media output**

Add exact exclusions for `config/channel.yaml`, `config/pipeline.yaml`, `secrets/`, `state/`, `cache/`, `failed/`, `logs/`, `runs/`, and common generated audio/video files while retaining `config/*.example.yaml`.

- [ ] **Step 2: Replace the Drive project-copy setup in README**

Document opening the canonical notebook from GitHub or copying only that notebook to Drive. State that the notebook clones the public repo on each fresh runtime and list the data retained in Drive.

- [ ] **Step 3: Run focused documentation and ignore checks**

Run: `rg -n "MayzCats-Automation/project|copies the wrapper source|Copy this entire project" README.md MayzCats_V1_Colab.ipynb`

Expected: no matches.

Run: `git check-ignore .env config/channel.yaml config/pipeline.yaml secrets/token.json state/runs.jsonl cache/tts/item/narration.mp3 logs/run.log runs/id/final.mp4`

Expected: every supplied private/runtime path is printed.

### Task 3: Verify, publish, and record the remote

**Files:**
- Track: all non-ignored project files
- Modify: Git metadata only

**Interfaces:**
- Consumes: verified local `main` branch
- Produces: public `https://github.com/m4mayz/mayzcats-automation`

- [ ] **Step 1: Run the complete offline verification**

Run: `python -m pytest -q`

Run: `python -m compileall -q src scripts`

Run: `python -m ruff check .`

Run: `python scripts/verify_notebook.py`

Run: `python -m build`

Expected: every command exits 0.

- [ ] **Step 2: Inspect exactly what the public commit will contain**

Run: `git add . && git status --short && git diff --cached --check`

Expected: no ignored private/runtime files and no whitespace errors.

- [ ] **Step 3: Scan staged text for common credential signatures**

Search staged files for private keys, provider key prefixes, refresh tokens, and access tokens. Expected: only documentation or variable-name references, with no credential values.

- [ ] **Step 4: Commit the implementation**

Run: `git commit -m "feat: load Colab source from GitHub"`

- [ ] **Step 5: Create and push the public GitHub repository**

Create public repository `m4mayz/mayzcats-automation` without generated starter files, add `origin` as `https://github.com/m4mayz/mayzcats-automation.git`, and push local `main` with upstream tracking.
