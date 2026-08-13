#!/usr/bin/env bash
# Jarvis setup for Pop!_OS / Ubuntu.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Jarvis setup (Pop!_OS) ==="

echo "[1/5] Installing system packages..."
sudo apt-get update
sudo apt-get install -y ffmpeg python3 python3-venv python3-pip git curl

echo "[2/5] Checking Node.js (Electron needs Node >= 18)..."
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | tr -d 'v' | cut -d. -f1)" -lt 18 ]; then
  echo "Installing Node 20 via NodeSource..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi

echo "[3/5] Creating Python venv and installing dependencies..."
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --upgrade pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/python/requirements.txt"

echo "[4/5] Installing Electron (npm)..."
npm install

echo "[5/5] Verifying environment..."
"$ROOT/.venv/bin/python" "$ROOT/scripts/check_deps.py"

echo ""
echo "=== Setup complete ==="
echo ""
echo "To launch:  npm start"
echo ""
echo "Optional one-time YouTube authorization:"
echo "  1. Create a Google Cloud project, enable 'YouTube Data API v3'"
echo "  2. Create an OAuth client ID (Desktop app), download JSON -> config/client_secret.json"
echo "  3. Run: python3 scripts/oauth_google.py"
echo ""
echo "To run the pipeline without the GUI:"
echo "  .venv/bin/python scripts/run_standalone.py --upload"
