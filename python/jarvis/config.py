"""Configuration loading with defaults merged from config/config.yaml."""
from __future__ import annotations

import os
from typing import Any, Optional

import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _ensure_venv_on_path() -> None:
    """Make tools installed into the project venv (e.g. yt-dlp) visible to subprocesses."""
    for rel in (os.path.join(".venv", "bin"), os.path.join("python", ".venv", "bin")):
        bin_dir = os.path.join(PROJECT_ROOT, rel)
        if os.path.isdir(bin_dir):
            path = os.environ.get("PATH", "")
            if bin_dir not in path.split(os.pathsep):
                os.environ["PATH"] = bin_dir + os.pathsep + path
            return


_ensure_venv_on_path()

DEFAULTS: dict[str, Any] = {
    "channel": {
        "niche": "AI & Tech News",
        "language": "en",
        "channel_name": "AI Pulse Daily",
        "voice": "en-US-ChristopherNeural",
        "auto_upload": False,
        "publish_in_future_hours": 0,
    },
    "video": {
        "format": "vertical",
        "width": 1080,
        "height": 1920,
        "max_duration_seconds": 75,
        "subtitles": True,
        "background_style": "tech",
    },
    "llm": {
        "provider": "openai",
        "base_url": "",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini",
    },
    "tts": {
        "provider": "edge",
        "voice": "en-US-ChristopherNeural",
        "rate": "+10%",
        "elevenlabs_api_key_env": "ELEVENLABS_API_KEY",
        "elevenlabs_voice_id": "",
    },
    "youtube": {
        "client_secrets": "config/client_secret.json",
        "token_path": "config/youtube_token.json",
        "category_id": "28",
    },
    "trends": {
        "rss_feeds": [
            "https://techcrunch.com/category/artificial-intelligence/feed/",
            "https://www.theverge.com/rss/index.xml",
            "https://venturebeat.com/category/ai/feed/",
            "https://blog.google/technology/ai/rss/",
        ],
        "yt_search_results": 6,
        "min_recency_hours": 72,
        "keyword_bonus": 15,
    },
    "output": {"dir": "output"},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict[str, Any], path: Optional[str] = None):
        self.data = data
        self.path = path

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def c(self, *keys: str) -> Any:
        return self.get(*keys)

    def root(self) -> str:
        return PROJECT_ROOT

    def abs(self, rel: str) -> str:
        if os.path.isabs(rel):
            return rel
        return os.path.join(PROJECT_ROOT, rel)

    def output_dir(self) -> str:
        return self.abs(self.get("output", "dir", default="output"))

    def to_dict(self) -> dict:
        return self.data


def load_config(path: Optional[str] = None) -> Config:
    path = path or os.path.join(PROJECT_ROOT, "config", "config.yaml")
    user: dict = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            user = yaml.safe_load(fh) or {}
    return Config(deep_merge(DEFAULTS, user), path)


def save_config(cfg: Config, updates: dict[str, Any]) -> Config:
    cfg.data = deep_merge(cfg.data, updates)
    os.makedirs(os.path.dirname(cfg.path), exist_ok=True)
    with open(cfg.path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg.data, fh, sort_keys=False, allow_unicode=True)
    return cfg
