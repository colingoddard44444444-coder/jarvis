# Jarvis — Desktop AI Agent Hub for Automated YouTube

A desktop app for Pop!_OS / Ubuntu that runs a multi-agent pipeline to research
trending AI & tech stories, write scripts, generate voiceovers, edit videos with
burned subtitles, create thumbnails, and publish to YouTube — all from one UI.

```
Electron UI  ──stdin/stdout JSON-RPC──▶  Python orchestrator  ──▶  6 agents
                                                                    │
                                trend ─▶ script ─▶ voice ─▶ video ──┤
                                  │        │         │        │     │
                                  │        └─▶ thumbnail ──▶ upload ┴─▶ YouTube
```

## Agents

| Agent      | What it does                                                                 |
|------------|------------------------------------------------------------------------------|
| `trend`    | Scans AI/tech RSS feeds, then checks YouTube traction via yt-dlp to pick the trendiest story |
| `script`   | LLM (OpenAI-compatible) writes hook, sentences, title, description, tags     |
| `voice`    | Free edge-tts neural voiceover per sentence (ElevenLabs optional)            |
| `video`    | Ken Burns montage + burned subtitles + narration → final MP4 (ffmpeg only)   |
| `thumbnail`| 1280×720 click-worthy thumbnail via Pillow                                   |
| `upload`   | Uploads to YouTube via the official Data API v3 (private by default)         |

## Install (Pop!_OS)

```bash
git clone <this repo> ~/jarvis
cd ~/jarvis
./scripts/setup_popos.sh      # installs ffmpeg, python venv, node deps, electron
npm start                     # launch the desktop app
```

`setup_popos.sh` needs `sudo` (for apt). It installs ffmpeg, python3, node 20,
the Python deps into `.venv/`, and Electron.

## YouTube authorization (once)

Uploading requires a Google Cloud project with the **YouTube Data API v3** enabled:

1. https://console.cloud.google.com/apis/library/youtube.googleapis.com → Enable
2. https://console.cloud.google.com/apis/credentials → Create credentials →
   OAuth client ID → **Desktop app** → download JSON
3. In Jarvis: run the pipeline without upload → when it prompts, click
   *Select client_secret.json* — or copy the JSON to `config/client_secret.json` manually.
4. Run once from a terminal to authorize:
   ```bash
   python3 scripts/oauth_google.py
   ```
5. Re-run the upload. Videos upload as **private** (and can be scheduled in the future).

## Usage

In the UI:
- Type a topic or leave it blank to auto-pick the day's trend.
- Choose format (Vertical = Shorts / Horizontal), schedule hours, auto-upload.
- Click **Run Full Pipeline**. Watch the console. Outputs appear under `output/run_*`.

### CLI / headless

```bash
python3 scripts/run_standalone.py --upload --schedule-hours 3
python3 scripts/run_standalone.py --topic "OpenAI news" --format vertical
```

## Configuration (`config/config.yaml`)

- `channel.voice` — edge-tts voice (e.g. `en-US-ChristopherNeural`)
- `llm.*` — provider, model, `api_key_env` (set that env var, e.g. `OPENAI_API_KEY`)
  - For a free/local LLM, set `provider: openai`, `base_url: http://localhost:11434/v1`, `model: llama3.1` (Ollama).
- `tts.provider` — `edge` (free) or `elevenlabs` (set `ELEVENLABS_API_KEY`)
- `video.format` — `vertical` / `horizontal`
- `channel.auto_upload` — default upload behavior

If the LLM is unavailable or errors, the script writer falls back to a template
script so the pipeline still completes.

## Requirements

- Pop!_OS / Ubuntu (or any distro with ffmpeg + Python 3.9+ + Node 18+)
- ~6 GB free disk for Electron + deps
- Network for RSS feeds, edge-tts, yt-dlp, and (optionally) your LLM provider

## Notes / disclaimers

- Generated videos are original content assembled from AI-generated assets
  (synthetic voiceover, generated backgrounds). Respect YouTube's Community
  Guidelines and your LLM provider's terms.
- yt-dlp scraping of view counts for trend ranking is done sparingly; the
  primary trend signal comes from news RSS feeds.
