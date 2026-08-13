"""Trend research: fetch AI/tech news via RSS and gauge YouTube traction via yt-dlp."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from typing import Optional

import feedparser

AI_KEYWORDS = [
    "ai", "artificial intelligence", "gpt", "llm", "neural", "openai", "anthropic",
    "claude", "gemini", "model", "robot", "machine learning", "deep learning",
    "nvidia", "chip", "semiconductor", "agence", "agent", "startup", "google",
    "meta", "microsoft", "apple", "amazon", "tesla", "vision pro", "quantum",
]


def _published_utc(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t and len(t) >= 6:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return datetime.now(timezone.utc)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _feed_weight(url: str) -> int:
    if "techcrunch" in url:
        return 3
    if "venturebeat" in url:
        return 3
    if "theverge" in url:
        return 2
    if "blog.google" in url:
        return 2
    return 1


def fetch_stories(cfg, limit: int = 12) -> list[dict]:
    now = datetime.now(timezone.utc)
    stories: list[dict] = []
    seen = set()

    for url in cfg.get("trends", "rss_feeds", default=[]):
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for entry in feed.entries[:10]:
            title = _strip_html(entry.get("title", ""))
            if not title or len(title) < 12:
                continue
            norm = re.sub(r"[^a-z0-9]+", "", title.lower())
            if norm in seen:
                continue
            seen.add(norm)
            link = entry.get("link", "")
            published = _published_utc(entry)
            hours_ago = max(0.0, (now - published).total_seconds() / 3600.0)
            summary = _strip_html(entry.get("summary", ""))
            if len(summary) < 40 and entry.get("description"):
                summary = _strip_html(entry.get("description", ""))
            recency = max(0.0, 100.0 - hours_ago * 1.5)
            haystack = (title + " " + summary[:220]).lower()
            keywords = sum(1 for k in AI_KEYWORDS if k in haystack)
            keywords = min(keywords, 5)
            bonus = cfg.get("trends", "keyword_bonus", default=15)
            if hours_ago > cfg.get("trends", "min_recency_hours", default=72) * 2:
                bonus = 0
            score = recency + keywords * bonus + _feed_weight(url)
            stories.append({
                "title": title,
                "summary": summary[:400],
                "link": link,
                "published": published.isoformat(),
                "hours_ago": round(hours_ago, 1),
                "score": round(score, 1),
                "source": _feed_weight(url),
            })
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories[:limit]


def yt_traction(query: str, n: int = 8) -> Optional[dict]:
    """Median views + count of recent YouTube videos matching a query (via yt-dlp)."""
    cmd = [
        "yt-dlp", "--skip-download", "--no-warnings", "--quiet",
        "--print", "%(view_count)s|%(title)s",
        f"ytsearch{n}:{query}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    views = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split("|", 1)
        if parts and parts[0].isdigit():
            views.append(int(parts[0]))
    if not views:
        return None
    views.sort()
    median = views[len(views) // 2]
    return {"median_views": median, "top_view": views[-1], "count": len(views)}


def pick_topic(cfg, stories: list[dict], min_hours: Optional[float] = None, traction_checks: int = 3) -> dict:
    min_hours = min_hours if min_hours is not None else cfg.get("trends", "min_recency_hours", default=72)
    candidates = [s for s in stories if s["hours_ago"] <= min_hours] or stories[:traction_checks]
    candidates = candidates[:traction_checks]
    best, best_score = None, -1.0
    for story in candidates:
        traction = yt_traction(story["title"][:60], n=cfg.get("trends", "yt_search_results", default=6))
        traction_score = 0.0
        if traction:
            traction_score = min(50.0, traction["median_views"] / 20000.0 * 10.0)
        story["traction"] = traction
        total = story["score"] + traction_score
        if total > best_score:
            best, best_score = story, total
    if best is None:
        raise RuntimeError("No trends found. Check network and RSS feeds in config.yaml.")
    best["trend_score"] = round(best_score, 1)
    return best


def find_extra_facts(topic: str) -> str:
    """Best-effort extra context for the script writer via a web search snippet."""
    try:
        query = topic.replace(" ", "+")
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "20", f"https://r.jina.ai/http://www.google.com/search?q={query}"],
            capture_output=True, text=True,
        )
        text = proc.stdout
        if len(text) > 300:
            lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith(("http", "Google", "Sign in"))]
            return " ".join(lines[:12])[:1500]
    except Exception:
        pass
    return ""
