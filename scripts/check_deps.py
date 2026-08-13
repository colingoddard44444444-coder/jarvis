"""Environment check — run via: python3 scripts/check_deps.py"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

CHECKS = [
    ("python", lambda: sys.version_info >= (3, 9)),
    ("ffmpeg", lambda: _binary("ffmpeg")),
    ("ffprobe", lambda: _binary("ffprobe")),
    ("yt-dlp", lambda: _binary("yt-dlp")),
    ("requests", lambda: importlib.util.find_spec("requests")),
    ("PyYAML", lambda: importlib.util.find_spec("yaml")),
    ("feedparser", lambda: importlib.util.find_spec("feedparser")),
    ("edge-tts", lambda: importlib.util.find_spec("edge_tts")),
    ("Pillow", lambda: importlib.util.find_spec("PIL")),
    ("googleapiclient", lambda: importlib.util.find_spec("googleapiclient")),
]

REQUIRED = ["ffmpeg", "ffprobe", "yt-dlp", "requests", "PyYAML", "feedparser", "edge-tts", "Pillow"]
OPTIONAL = ["googleapiclient"]


def _binary(name: str) -> bool:
    try:
        subprocess.run([name, "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def main() -> None:
    missing = []
    print("Jarvis environment check\n" + "=" * 30)
    for name, fn in CHECKS:
        ok = bool(fn())
        status = "OK " if ok else "MISS"
        print(f"  [{status}] {name}")
        if not ok and name in REQUIRED:
            missing.append(name)
    if missing:
        print("\nRun: scripts/setup_popos.sh  (installs ffmpeg + python deps)")
        sys.exit(1)
    if any(not fn() for name, fn in CHECKS if name in OPTIONAL):
        print("\nNote: googleapiclient missing — uploads disabled until 'pip install -r requirements.txt'.")
    print("\nAll required tools present.")


if __name__ == "__main__":
    main()
