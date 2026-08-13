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

## Need help?

```bash
cd ~/jarvis && python3 scripts/check_deps.py
```

Full docs: **README.md** in this repo.
