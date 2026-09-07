# MayzCats V1 Design

## Objective

Build a Google Colab-ready pipeline that creates one factual English YouTube
Short about cats and uploads it with configured `privacyStatus=private` or
`privacyStatus=public`. The pipeline checkpoints completed stages and paid TTS
artifacts in Google Drive so interrupted runs can continue without buying the
same narration again. Temporary render files and completed checkpoints are
removed after a successful upload; the content-addressed TTS cache remains.

## Fixed product rules

- Channel: MayzCats, English, family-friendly, audience 13+.
- Content mix: 80% evergreen and 20% trending; at most 20 candidates per run.
- A topic enters the 90-day history only after `videos.insert` returns a video ID.
- Duplicate detection compares both subject meaning and substantive angle.
- Research uses Tavily and retains internal source traces. Script facts must be
  grounded in the retained results; health content adds a vet disclaimer and
  cannot diagnose or prescribe treatment.
- ElevenLabs voice: Jessica (`cgSgspJ2msm6clMCkdW9`), model
  `eleven_multilingual_v2`, speed `1.08`, with API keys tried sequentially.
- Accept narration from 35 through 55 seconds. Outside that range, revise the
  script and retry TTS up to the configured bounded attempt count.
- Prefer real cat video from Pexels and Pixabay, then still images. Images may
  receive subtle pan/zoom; source videos may not receive artificial pan/zoom.
- Output: H.264/AAC MP4, 1080x1920, 30 fps. Montserrat Bold subtitles are
  center-bottom, at most five words per line and two lines. Use word highlighting
  when timing exists and phrase-level subtitles otherwise.
- The first 1-2 seconds use the strongest visual and a large hook. The
  `MayzCats` text watermark stays at top-right. Most transitions are hard cuts.
- Select a track from the checked-out MoneyPrinterTurbo `resource/songs`
  directory, validate and checkpoint it before paid TTS, and mix at 0.08
  without automatic ducking. Record the filename, source URL, SHA-256, and the
  upstream-unverified license status without blocking either upload privacy.
- YouTube metadata is truthful and concise. Category is Pets & Animals (`15`),
  made-for-kids is false, and privacy accepts `private` or `public` from
  `config/pipeline.yaml`.
- Keep MoneyPrinterTurbo unmodified. Invoke its public CLI as a subprocess to
  assemble pre-timed local scene clips with prepared narration; apply MayzCats
  subtitles, watermark, music, and output normalization in an external final
  FFmpeg pass.

## Runtime architecture

The notebook mounts Drive, materializes default configuration without replacing
user files, installs this wrapper, installs an isolated MoneyPrinterTurbo
environment, checks FFmpeg/Montserrat/secrets, and invokes the pipeline once.

The pipeline uses these boundaries:

1. `config` and `storage` establish Drive and ephemeral run directories.
2. `topic_engine`, `dedup`, and `history` choose an unused candidate.
3. `research` and `script_writer` produce a source-grounded brief and script.
4. `media_fetcher` downloads reusable visual assets and `music_fetcher` selects
   and validates a bundled MPT song. Both complete before paid TTS.
5. `elevenlabs_tts` produces audio plus character-derived word timings;
   `tts_cache` stores both by a hash of every synthesis input.
6. `scene_planner` builds adaptive timings after narration duration is known.
7. `video_engine` preprocesses exact-length scene clips, asks the untouched MPT
   CLI to assemble them, then burns ASS overlays and mixes music.
8. `youtube_upload` performs OAuth and a resumable private or public upload.
9. `pipeline` commits history only on success. On upload failure it copies a
   complete retry package to Drive, including the MP4 and upload payload.

All external services are behind small injectable clients. Unit tests use local
fixtures and fakes; the preflight command checks the live Colab environment
without spending API quota. A live end-to-end run is deliberately not performed
by the local test suite because it requires the user's secrets, paid TTS quota,
media downloads, and YouTube consent.

## Persistent layout

```text
MyDrive/MayzCats-Automation/
├── config/channel.yaml
├── config/pipeline.yaml
├── secrets/.env
├── secrets/youtube/client_secret.json
├── secrets/youtube/token.json
├── state/topic_history.json
├── state/runs.jsonl
├── runs/<run-id>/
├── cache/tts/<input-hash>/
├── failed/<run-id>/
└── logs/
```

The project source may be stored separately under
`MyDrive/MayzCats-Automation/project` for notebook upload-based setup. It is not
runtime state and is never modified by the pipeline.

## Failure and recovery

Service errors are explicit and redact credentials. Invalid LLM JSON,
inadequate research, exhausted TTS keys, missing MPT music, media shortage, MPT
failure, FFmpeg failure, and OAuth failure stop the run and append a failed run
record. Every completed stage has a Drive artifact. `resume_latest` or an
explicit run ID reloads these artifacts and continues at the first incomplete
stage. Only failures after a final MP4 exists additionally create the complete
upload-only package. Neither failure path marks the topic as used.
