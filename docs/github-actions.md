# GitHub Actions deployment

Runtime branch: `codex/github-actions`. The only file installed on `main` is
`.github/workflows/mayzcats-schedule.yml`, copied from
`docs/github-actions-dispatcher.yml`. It calls the reusable runtime workflow.

The dispatcher wakes at minute 17 hourly. The runner executes at most once per
five-hour UTC epoch slot, including across midnight (unlike cron `*/5`).
GitHub can delay or drop scheduled events. This is approximately every five hours,
not a precise timer. Manual dispatch can force a run.

## Repository Secrets

Configure these under Settings -> Secrets and variables -> Actions.
The active config selects Gemini Interactions:

```yaml
llm:
  provider: gemini
  model: gemini-3.8-flash
  api_revision: "2026-05-20"
```

For Gemini, add `GEMINI_API_KEY`; no OPENAI secrets are required.
For the existing OpenAI-compatible provider, set `llm.provider: openai` and supply:

- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

Required for both providers:

- `ELEVENLABS_API_KEYS` (comma-separated)
- `TAVILY_API_KEY`
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`
- `YOUTUBE_CLIENT_SECRET_JSON` (contents of OAuth client_secret.json)
- `YOUTUBE_TOKEN_JSON` (contents of authorized token.json, including refresh_token)

Gemini uses POST /v1beta/interactions, x-goog-api-key and Api-Revision headers,
JSON text responses and store=false. All editorial stages and semantic duplicate
checks use the selected provider, including upload-only retry. Existing timeout
and retry settings under network also apply to Gemini.
See [Google's Interactions documentation](https://ai.google.dev/gemini-api/docs/get-started).

Obtain initial YouTube consent once using the existing OAuth flow. Actions cannot
prompt for login. The runner refreshes the access token per run; it never commits
token.json or includes credentials in artifacts. If authorization is revoked or the
refresh token expires, replace the token secret. No personal GitHub PAT is required:
the workflow uses GITHUB_TOKEN with contents:write and actions:read.

## Storage

| Data | Location |
| --- | --- |
| Code, music, dependencies | Runtime branch |
| Active config | config/channel.yaml and config/pipeline.yaml |
| Published topic history, compact run log, scheduler pointer | state/ on runtime branch |
| Checkpoints, TTS cache, failed videos, logs, archived final videos | runtime-RUN_ID Actions artifact |
| Credentials | GitHub Secrets; temporary runner files only |
| FFmpeg intermediates | Ephemeral runner disk |

This public repository also has public state and downloadable artifacts. Only
selected publication fields enter Git; source bodies and local paths are omitted.
The 21 supplied publication entries seed the topic history; keep them to avoid
regenerating old topics. Config currently retains the previous private upload
default: change youtube.privacy in config/pipeline.yaml to public when desired.

Each attempt restores the previous artifact and saves a new snapshot (90-day
retention). Artifacts consume GitHub storage quota; caches/videos accumulate in the
snapshot. If restore fails, the workflow stops, so inspect Actions before forcing
a fresh run. Secrets are excluded by an explicit upload path allowlist.

Auto mode resumes the pending checkpoint. For an irrecoverable or duplicate topic,
manually dispatch with mode=new to start a new topic. State is committed on both
success and failure. Pipeline runs are serialized; avoid concurrent Colab publishing.
Do not cancel an upload in progress: interruption after YouTube accepts a video
but before state persistence may require manual reconciliation in YouTube Studio.

CPU Torch is installed from the official CPU wheel index to fit hosted-runner disk.
Wrapper dependencies follow pyproject.toml; vendored MPT uses its frozen lockfile.
No Google Drive mount is used. LLM, stock media, ElevenLabs and YouTube remain the
existing API providers; all compute and persistent file storage are on GitHub.

To pause, disable the dispatcher in the Actions UI. An inactive public repository's
schedule may be disabled by GitHub. To recover a missing artifact, download an
available runtime artifact and update state/actions.json snapshot_run_id to its run
ID, or clear pending_run and snapshot_run_id to explicitly abandon that recovery.
