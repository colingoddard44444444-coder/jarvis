# Jarvis — Quick Start (Pop!_OS)

Copy-paste these one at a time into a Pop OS terminal.

## 1. Install everything (one time)

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/colingoddard44444444-coder/jarvis.git ~/jarvis
cd ~/jarvis
./scripts/setup_popos.sh
```

> `setup_popos.sh` needs sudo and takes a few minutes. It installs ffmpeg,
> Python 3 + venv + pip, Node 20, the Python dependencies, and Electron.

## 2. Launch Jarvis

```bash
cd ~/jarvis
npm start
```

The desktop app opens. Click **▶ Run Full Pipeline** to generate a video.

- **Topic** — leave blank to auto-pick today's AI/tech trend, or type one.
- **Format** — Vertical (Shorts) or Horizontal.
- **Publish in (h)** — hours from now to schedule on YouTube (0 = no schedule).
- **Auto-upload** — tick to publish; otherwise it just makes the video.

Videos land in `~/jarvis/output/run_*`.

## 3. Set your LLM key (better scripts)

The script writer needs an LLM API key, or it falls back to a template script.

```bash
echo 'export OPENAI_API_KEY="sk-your-key"' >> ~/.bashrc
source ~/.bashrc
```

(Or run without it — videos still generate using the template script.)

## 4. YouTube upload (optional, one time)

1. Create a Google Cloud project: https://console.cloud.google.com
2. Enable the **YouTube Data API v3**.
3. Create an OAuth client ID (**Desktop app**) and download the JSON.
4. Put it here on your PC:
   ```bash
   cp /path/to/downloaded/file.json ~/jarvis/config/client_secret.json
   ```
5. Authorize once:
   ```bash
   cd ~/jarvis
   python3 scripts/oauth_google.py
   ```
6. Re-run the pipeline with **Auto-upload** ticked (uploads as private).

## 5. Voice control (optional)

```bash
pip install vosk            # offline speech-to-text (~40 MB model auto-downloads)
```

Then in the app: the **Voice Control** panel has **HOLD TO TALK** (hold, speak,
release — Jarvis acts on your command) and a **Wake word** toggle so you can
just say "Jarvis" from across the room.

Try: *"make a video about AI"*, *"upload to YouTube"*, *"what's the status"*,
*"turn on autopilot"*.

## 6. Autopilot (autonomous mode)

The **Autopilot** panel makes the whole thing self-running:

1. Toggle **Autonomous mode** ON.
2. Set **Every (h)** — how often to produce a new video (default 6).
3. Jarvis researches the day's top AI/tech trend, writes the script, renders the
   video and (if **auto-upload** is on and YouTube is authorized) posts it.

The `config/config.yaml` → `autopilot` section also supports `max_per_day`
(a daily cap) and a fixed `topic` (leave `""` for auto-trending).

## 7. Run Jarvis from your phone (Termux)

The whole backend runs on the phone with a mobile web panel — no desktop needed.

```bash
pkg install -y git python ffmpeg        # one time, if not installed
cd ~
git clone https://github.com/colingoddard44444444-coder/jarvis.git
cd ~/jarvis
python3 -m pip install -r python/requirements.txt   # one time
python3 python/web_server.py
```

Then open `http://127.0.0.1:8077` in your phone's browser (Chrome works best).
From the panel you can:

- **Tap & Speak** — talk; Jarvis hears you via your browser's mic and replies
  (try "make a video about AI", "what's the status", "turn on autopilot").
- Toggle **Autonomous mode** and watch it produce videos on a schedule.
- Watch finished videos under **Outputs** (tap "watch").

To reach it from another device on your Wi-Fi, run `python3 python/web_server.py 0.0.0.0:8077`
and open `http://<your-phone-ip>:8077`.

## Need help?

```bash
cd ~/jarvis && python3 scripts/check_deps.py
```

Full docs: **README.md** in this repo.
