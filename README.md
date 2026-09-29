# MayzCats V1

MayzCats V1 is a YouTube Shorts automation pipeline that runs on GitHub Actions,
with a vendored [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)
runtime snapshot. It researches one factual cat topic, rejects previously published
topic families, renders a 1080x1920 Short with Jessica narration and MayzCats
overlays, then uploads it to YouTube.

All compute and persistent file storage are on GitHub: code, config, and state live
in this repository, and checkpoints and caches live in Actions artifacts. LLM, stock
media, ElevenLabs, and YouTube are the external API providers.

## What is implemented

- Custom OpenAI-compatible `/chat/completions` client, plus the Gemini
  Interactions API as an alternative provider.
- Tavily trend discovery, research, fact-grounded brief generation, and retained
  internal source trace.
- All-history topic rejection using known aliases, sentence embeddings, and a
  strict LLM semantic check. Changing the angle does not unlock a used topic.
  Generation receives published subjects; resume and upload-only retry also check
  history. Invalid semantic verdicts stop the run before publication.
- ElevenLabs Jessica (`cgSgspJ2msm6clMCkdW9`), multilingual v2, speed 1.08,
  character timing, sequential key fallback for explicit provider rejection,
  and a content-addressed TTS cache that prevents regenerating identical
  narration after later-stage failures.
- Pexels and Pixabay real-video-first sourcing with image fallback and creator,
  page, and license trace.
- Music selected from the 29 MoneyPrinterTurbo tracks vendored under
  `src/music`, validated and copied to the run checkpoint before paid TTS starts.
  Metadata records the exact filename, SHA-256, and MPT source. MPT documents
  these bundled tracks as originating from YouTube and does not provide a
  verified per-track license; MayzCats records that status without blocking the
  configured upload privacy.
- Adaptive scene durations, a 1-2 second opening visual, still-image-only subtle
  pan/zoom, stable ASS karaoke phrases with two-line portrait-safe wrapping,
  Montserrat Bold, top-right MayzCats watermark, and 0.08 music mix.
- Vendored MPT CLI composition followed by a MayzCats FFmpeg pass normalized to
  H.264/AAC, 1080x1920, 30 fps.
- YouTube Data API OAuth, resumable upload, category 15, made-for-kids false,
  configurable `private` or `public` status, and scheduled publication.
- History commit and local cleanup only after YouTube returns a video ID.
- Complete failed-upload package and upload-only retry without regenerating.
- Checkpoints for topic, research, script, media, music, TTS, render, and upload,
  resumed automatically by the next scheduled run.

## Schedule

`.github/workflows/github-runner.yml` runs on `main` at 07:00 and 14:00 WIB
(00:00 and 07:00 UTC). Each scheduled run uploads the video as private with a
YouTube `publishAt` of 16:00 or 23:00 WIB respectively, so publication time stays
stable even when GitHub delays a scheduled event.

Manual dispatch (Actions -> MayzCats GitHub runner -> Run workflow) uploads
immediately with the configured privacy. Its inputs:

- `force`: run even if the current 5-hour slot already ran (default true).
- `mode`: `auto` resumes the pending checkpoint; `new` abandons it and starts a
  new topic.

To pause, disable the workflow in the Actions UI.

## Repository Secrets

Configure these under Settings -> Secrets and variables -> Actions.
The active config uses Groq through the OpenAI-compatible provider:

```yaml
llm:
  provider: openai
  model: openai/gpt-oss-120b
```

For this provider, supply:

- `OPENAI_BASE_URL` (for Groq: `https://api.groq.com/openai/v1`)
- `OPENAI_API_KEY`

To switch to Gemini Interactions instead, set `llm.provider: gemini`, pick a Gemini
`llm.model`, and add `GEMINI_API_KEY`; no OPENAI secrets are required then.
The model name is not a secret; set it once as `llm.model` in
`config/pipeline.yaml`. Both API key secrets accept a comma-separated list and
rotate to the next key on a quota or auth rejection.

Required for both providers:

- `ELEVENLABS_API_KEYS` (comma-separated)
- `TAVILY_API_KEY`
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`
- `YOUTUBE_CLIENT_SECRET_JSON` (contents of the OAuth `client_secret.json`)
- `YOUTUBE_TOKEN_JSON` (contents of an authorized `token.json`, including
  `refresh_token`)

If any secret is missing, the workflow skips the run with a warning.

### YouTube authorization

Actions cannot prompt for login, so create `token.json` once on your own machine:

1. In Google Cloud Console, enable **YouTube Data API v3**, configure the OAuth
   consent screen, and create an OAuth client with application type
   **Desktop app**. If the consent screen is in testing, add the MayzCats Google
   account as a test user.
2. Save the client JSON as `client_secret.json`, then run:

   ```text
   python -c "from pathlib import Path; from mayzcats.youtube_upload import load_credentials; load_credentials(Path('client_secret.json'), Path('token.json'))"
   ```

3. Open the printed URL and approve. The browser then tries to open a localhost URL
   that does not load; copy that full URL from the address bar and paste it into
   the prompt.
4. Paste the contents of `client_secret.json` and `token.json` into the two
   YouTube secrets, then delete the local copies.

The runner refreshes the access token on every run. It never commits `token.json`
or includes credentials in artifacts. If authorization is revoked or the refresh
token expires, repeat these steps and replace `YOUTUBE_TOKEN_JSON`. No personal
GitHub PAT is required: the workflow uses `GITHUB_TOKEN` with `contents: write` and
`actions: read`.

## Configuration

Active config is `config/channel.yaml` and `config/pipeline.yaml` on `main`.
Uploads currently use `youtube.privacy: public`; set it to `private` to hold
uploads for review. Category, made-for-kids, voice ID, size, and frame-rate rules
remain fixed for V1.

If YouTube flags a bundled track, add its filename to `config/pipeline.yaml` so
future runs skip it:

```yaml
music:
  volume: 0.08
  provider: moneyprinterturbo_builtin
  excluded_files:
    - output000.mp3
```

## Storage

| Data | Location |
| --- | --- |
| Code, music, dependencies | `main` |
| Active config | `config/channel.yaml` and `config/pipeline.yaml` |
| Published topic history, compact run log, scheduler pointer | `state/` on `main` |
| Checkpoints, TTS cache, failed videos, logs, archived final videos | `runtime-RUN_ID` Actions artifact |
| Credentials | GitHub Secrets; temporary runner files only |
| FFmpeg intermediates | Ephemeral runner disk |

This public repository also has public state and downloadable artifacts. Only
selected publication fields enter Git; source bodies and local paths are omitted.
The seeded publication entries in `state/topic_history.json` prevent regenerating
old topics; keep them.

Each attempt restores the previous artifact and saves a new snapshot (90-day
retention). Artifacts consume GitHub storage quota, and caches and videos
accumulate in the snapshot. Secrets are excluded by an explicit upload path
allowlist.

CPU Torch is installed from the official CPU wheel index to fit hosted-runner disk.
Wrapper dependencies follow `pyproject.toml`; vendored MPT uses its frozen lockfile.

## Recovery

- State is committed to `main` after every attempt, on success and failure.
  The bot commits are `chore(state): record Actions run [skip ci]`.
- `auto` mode resumes the checkpoint in `state/actions.json` `pending_run`. Each
  completed stage is skipped, so a run that fails after TTS does not call
  ElevenLabs again. A duplicate-topic checkpoint is abandoned automatically and
  another topic is tried.
- For an irrecoverable checkpoint, manually dispatch with `mode=new`.
- If the snapshot artifact is missing, download an available `runtime-*` artifact
  and set `snapshot_run_id` in `state/actions.json` to its run ID, or clear
  `pending_run` and `snapshot_run_id` to abandon that recovery.
- Runs are serialized by a concurrency group. Do not cancel an upload in
  progress: interruption after YouTube accepts a video but before state
  persistence may require manual reconciliation in YouTube Studio.

Checkpoint layout inside the artifact:

```text
runs/<RUN_ID>/        state.json, candidate.json, research.json, script.json,
                      media.json, media/, music.json, music/, narration.json,
                      render.json, final.mp4, post_payload.json, upload.json
cache/tts/<HASH>/     narration.mp3, manifest.json
failed/<RUN_ID>/      final.mp4, post_payload.json, run.json, script.txt,
                      sources.json, music.json, error.log
```

## Verification

Offline checks do not call LLM, Tavily, ElevenLabs, media, or YouTube services:

```text
python -m pytest -q
python -m compileall -q src scripts
ruff check .
python -m build
```

On the runner, `mayzcats.preflight` checks FFmpeg, fonts, MPT, music, and secrets
before any paid API call. A true end-to-end check requires live keys, paid TTS
quota, stock-media downloads, and a YouTube upload; the local test suite cannot
claim that.

## Service references

- [MoneyPrinterTurbo CLI](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/README-en.md)
- [ElevenLabs speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [Pexels API](https://www.pexels.com/api/documentation/)
- [Pixabay API](https://pixabay.com/api/docs/)
- [YouTube videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [Gemini Interactions API](https://ai.google.dev/gemini-api/docs/get-started)
