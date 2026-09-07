# MayzCats V1

MayzCats V1 is a Google Colab-ready wrapper around an untouched
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) checkout. It
researches one factual cat topic, rejects recent semantic subject-and-angle
duplicates, renders a 1080x1920 Short with Jessica narration and MayzCats
overlays, then uploads it to YouTube using the configured **Private** or
**Public** privacy status. The default remains `private`.

## What is implemented

- Google Drive state and credential persistence under
  `MyDrive/MayzCats-Automation`.
- Custom OpenAI-compatible `/chat/completions` client.
- Tavily trend discovery, research, fact-grounded brief generation, and retained
  internal source trace. Medical scripts deterministically retain the research
  disclaimer even when the LLM omits it during drafting or duration revision.
- 90-day semantic duplicate detection across both subject and substantive angle
  with `sentence-transformers/all-MiniLM-L6-v2`.
- ElevenLabs Jessica (`cgSgspJ2msm6clMCkdW9`), multilingual v2, speed 1.08,
  character timing, sequential key fallback for explicit provider rejection,
  and a content-addressed Drive cache that prevents regenerating identical
  narration after later-stage failures.
- Pexels and Pixabay real-video-first sourcing with image fallback and creator,
  page, and license trace.
- Music selected from the checked-out MoneyPrinterTurbo `resource/songs`
  library, validated and copied to the Drive checkpoint before paid TTS starts.
  Metadata records the exact filename, SHA-256, and MPT source. MPT documents
  these bundled tracks as originating from YouTube and does not provide a
  verified per-track license; MayzCats records that status without blocking the
  configured upload privacy.
- Adaptive scene durations, a 1-2 second opening visual, still-image-only subtle
  pan/zoom, stable ASS karaoke phrases with two-line portrait-safe wrapping,
  Montserrat Bold, top-right MayzCats watermark, and 0.08 music mix.
- External MPT CLI composition followed by a MayzCats FFmpeg pass normalized to
  H.264/AAC, 1080x1920, 30 fps.
- YouTube Data API OAuth, resumable upload, category 15, made-for-kids false,
  and configurable `private` or `public` status.
- History commit and local cleanup only after YouTube returns a video ID.
- Complete failed-upload package and upload-only retry without regenerating.
- Drive checkpoints for topic, research, script, media, music, TTS, render, and
  upload, with `resume_latest` or explicit run-ID recovery.

## Google Colab and Drive setup

1. Open the canonical
   [MayzCats notebook](https://github.com/m4mayz/mayzcats-automation/blob/main/MayzCats_V1_Colab.ipynb)
   in Google Colab. You may copy only the notebook to Drive for convenient launching.

2. Choose **Runtime -> Run all**. The notebook shallow-clones this public
   repository into the temporary Colab runtime, creates the persistent Drive
   directories and example configuration, then stops at preflight until the
   required credentials exist.

3. Edit this generated file in Drive:

    ```text
    MyDrive/MayzCats-Automation/secrets/.env
    ```

    Fill these values without adding quotes unless a value itself requires them:

    ```dotenv
    OPENAI_BASE_URL=https://your-compatible-host.example/v1
    OPENAI_API_KEY=your-key
    OPENAI_MODEL=your-model
    ELEVENLABS_API_KEYS=key1,key2,key3,key4
    PEXELS_API_KEY=your-key
    PIXABAY_API_KEY=your-key
    TAVILY_API_KEY=your-key
    ```

    `OPENAI_BASE_URL` must be the API base whose child endpoint is
    `/chat/completions`. A local-only URL on your own computer is not reachable
    from a hosted Colab runtime; use a network-reachable compatible endpoint.

4. In Google Cloud Console, enable **YouTube Data API v3**, configure the OAuth
   consent screen, create an OAuth client with application type **Desktop app**,
   and download its JSON to:

    ```text
    MyDrive/MayzCats-Automation/secrets/youtube/client_secret.json
    ```

    If the consent screen is in testing, add the MayzCats Google account as a
    test user.

5. Optional: edit `MyDrive/MayzCats-Automation/config/channel.yaml` and
   `MyDrive/MayzCats-Automation/config/pipeline.yaml`. To upload publicly,
   set:

    ```yaml
    youtube:
      privacy: public
    ```

    Supported values are `private` and `public`. Category, made-for-kids,
    voice ID, size, and frame-rate rules remain fixed for V1.

## Run

Choose **Runtime → Run all**. The notebook:

1. mounts Drive and clones the wrapper source from GitHub to `/content`;
2. installs FFmpeg when missing, obtains Montserrat directly from the official
   Google Fonts repository, installs wrapper dependencies, and creates an
   isolated Python 3.11 MPT environment;
3. clones or refreshes MPT under `/content/mayzcats/MoneyPrinterTurbo` without
   modifying its source;
4. completes or refreshes YouTube OAuth in the notebook kernel before paid API
   stages;
5. runs preflight; and
6. creates or resumes one Short and uploads it using the configured privacy.

On the first YouTube authorization, open the printed Google URL. After approval,
the browser will try to open a localhost URL that cannot load from Colab. Copy
that entire URL from the browser address bar and paste it into the notebook
prompt. The resulting refreshable `token.json` is stored in Drive for later
runs.

Successful output is recorded in `state/runs.jsonl` and
`state/topic_history.json`. The `/content` run directory and completed Drive
checkpoint are deleted after the upload returns a video ID. The TTS cache is
retained under `cache/tts` so identical narration is never purchased twice.

## Run modes and resume

At the top of the notebook choose one mode:

```python
RUN_MODE = "new"            # create a new Short
RESUME_RUN_ID = ""
RERENDER_ON_RESUME = False
```

Resume the most recent failed checkpoint:

```python
RUN_MODE = "resume_latest"
RESUME_RUN_ID = ""
RERENDER_ON_RESUME = False
```

Or resume an exact run:

```python
RUN_MODE = "resume"
RESUME_RUN_ID = "abc1a6ae-86aa-4fb7-a489-6ba0b0166b3c"
RERENDER_ON_RESUME = False
```

Each successful stage is skipped on resume. Media, the selected MPT song,
narration audio/timings, and a rendered MP4 are persisted as soon as they are
ready. A run that fails after TTS therefore resumes without calling ElevenLabs.
The failure log also prints the exact run ID and resume command.

To rebuild a video after changing subtitles or rendering while keeping the
already-paid narration, resume the checkpoint with:

```python
RUN_MODE = "resume"
RESUME_RUN_ID = "5021c36a-dbcf-4e93-979f-1a6a352fa4de"
RERENDER_ON_RESUME = True
```

Only rendering and the subsequent upload run again. Topic selection, research,
script, downloaded media, selected music, and TTS are reused from Drive.

Persistent recovery data is stored as:

```text
runs/<RUN_ID>/
├── state.json
├── candidate.json
├── research.json
├── script.json
├── media.json
├── media/
├── music.json
├── music/
├── narration.json
├── render.json
├── final.mp4
├── post_payload.json
└── upload.json

cache/tts/<INPUT_HASH>/
├── narration.mp3
└── manifest.json
```

## Upload failure and retry

An upload failure after rendering creates:

```text
failed/<RUN_ID>/
├── final.mp4
├── post_payload.json
├── run.json
├── script.txt
├── sources.json
├── music.json
└── error.log
```

After fixing OAuth, quota, or connectivity, retry only the upload in a Colab
cell:

```python
!python -m mayzcats.pipeline \
  --drive-root /content/drive/MyDrive/MayzCats-Automation \
  --retry-upload RUN_ID
```

The retry preserves the privacy stored in `post_payload.json`. A successful
retry records history and removes the failed package and checkpoint.

## Verification

Offline checks do not call LLM, Tavily, ElevenLabs, media, or YouTube services:

```text
python -m pytest -q
python -m compileall -q src scripts
ruff check .
python scripts/verify_notebook.py
python -m build
```

Inside Colab, the notebook runs this environment check before spending API
quota:

```text
python -m mayzcats.preflight \
  --drive-root /content/drive/MyDrive/MayzCats-Automation \
  --mpt-root /content/mayzcats/MoneyPrinterTurbo
```

A true end-to-end verification requires the user's live keys, paid TTS quota,
stock-media downloads, Google consent, and a YouTube upload. The local test
suite intentionally cannot claim that live integration.

### Colab APT exit status 100

Current Colab images do not always expose the Ubuntu repository component that
contains `fonts-montserrat`. MayzCats therefore installs only FFmpeg/fontconfig
through APT and downloads the licensed Montserrat variable font from the
official Google Fonts repository. If an older notebook still tries to install
`ffmpeg fonts-montserrat` in one command, replace it with the current notebook
and `src/mayzcats/colab_bootstrap.py`, then restart **Runtime -> Run all**.

## Service references

- [MoneyPrinterTurbo CLI and Colab](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/README-en.md)
- [ElevenLabs speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [Pexels API](https://www.pexels.com/api/documentation/)
- [Pixabay API](https://pixabay.com/api/docs/)
- [YouTube videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
