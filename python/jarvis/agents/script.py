"""Agent 2/6 — Script Writer: LLM turns the trending story into a video script."""
from __future__ import annotations

from ..agent import Agent
from ..llm import LLM, LLMError, parse_json  # noqa: F401  (LLMError/parse_json re-used by callers)

SYSTEM_PROMPT = (
    "You are the head writer for a fast-growing AI & tech news YouTube channel. "
    "You write punchy, factual, short news scripts for vertical (Shorts-style) videos. "
    "Every claim must be grounded in the provided facts. Voice: energetic, clear, conversational. "
    "Output ONLY valid JSON, no markdown."
)

USER_TEMPLATE = """Write a news video script (about 60-75 seconds spoken, 9-12 short sentences) about this story.

STORY TITLE: {title}
SOURCE: {link}
PUBLISHED: {published} ({hours_ago}h ago)
SUMMARY: {summary}
EXTRA CONTEXT: {extra}

RULES:
- One sentence per list item. Each spoken sentence <= 150 chars.
- Line 1 is a strong attention-grabbing hook.
- Middle sentences explain the story with concrete facts and numbers only.
- Add one sentence of broader context/why it matters.
- Last line is a call to action (ask to subscribe/like).
- No filler, no invented facts, no hashtags inside sentences.

Return JSON exactly like:
{{
  "title": "youtube title, under 100 chars, curiosity-driven",
  "hook": "first spoken sentence",
  "sentences": ["sentence 2", "sentence 3", ...],
  "description": "2-3 sentence video description with 3 relevant hashtags",
  "tags": ["tag1", "tag2", "tag3", "tag4"]
}}
"""


class ScriptAgent(Agent):
    """Uses an LLM (OpenAI-compatible) to write the script, title, description and tags."""

    name = "script"

    def run(self, orch, ctx: dict, llm=None) -> dict:
        topic = self._resolve_topic(orch, ctx)
        self.log(f"Writing script for: {topic['title']}")
        llm = llm or LLM(orch.cfg)
        user = USER_TEMPLATE.format(
            title=topic["title"],
            link=topic.get("link", ""),
            published=topic.get("published", ""),
            hours_ago=topic.get("hours_ago", "?"),
            summary=(topic.get("summary") or "")[:800],
            extra=(topic.get("extra") or "")[:1200],
        )
        try:
            data = llm.chat_json(SYSTEM_PROMPT, user)
            self._validate(data)
        except Exception as exc:  # noqa: BLE001 - template fallback is the safety net
            self.log(f"LLM failed ({exc}), falling back to template script.", "warn")
            data = self._fallback(topic)

        sentences = [data["hook"]] + data["sentences"]
        sentences = self._clean_sentences(sentences)
        if ctx.get("params", {}).get("max_sentences"):
            sentences = sentences[: int(ctx["params"]["max_sentences"])]
        max_dur = orch.cfg.get("video", "max_duration_seconds", default=75)
        self.log(f"Script ready: {len(sentences)} sentences, ~{self._estimate_duration(len(sentences))}s")
        return {
            "title": data["title"],
            "hook": data["hook"],
            "sentences": sentences,
            "description": data["description"],
            "tags": data["tags"][:5],
            "max_duration": max_dur,
        }

    def _resolve_topic(self, orch, ctx: dict) -> dict:
        from .. import trends
        story = ctx.get("trend", {}).get("story")
        if story:
            return story
        if ctx.get("topic"):
            return {
                "title": ctx["topic"],
                "link": "",
                "summary": "",
                "extra": trends.find_extra_facts(ctx["topic"]),
            }
        self.log("No topic provided — running trend research first...")
        from .trend import TrendAgent
        return TrendAgent().run(orch, ctx)["story"]

    def _validate(self, data: dict) -> None:
        for key in ("title", "hook", "sentences", "description", "tags"):
            if key not in data:
                raise ValueError(f"LLM output missing '{key}'")
        if not isinstance(data["sentences"], list) or len(data["sentences"]) < 3:
            raise ValueError("LLM output sentences too short")
        if not isinstance(data["tags"], list):
            data["tags"] = []

    def _fallback(self, topic: dict) -> dict:
        title = topic["title"]
        summary = (topic.get("summary") or "").strip()
        lead = summary.split(". ")[0] + "." if summary else "The details are still emerging, and the whole industry is watching closely."
        sentences = [
            f"You won't believe what just happened in AI.",
            title,
            lead,
            "Here's why this matters right now.",
            f"According to the latest reports, {title.lower()} is changing the game.",
            "Experts say this could reshape the entire industry within months.",
            "This is exactly the kind of breakthrough to keep watching.",
            "If you want to stay ahead of the AI curve, hit subscribe and turn on notifications.",
            "Thanks for watching — see you in the next one.",
        ]
        return {
            "title": title[:95],
            "hook": sentences[0],
            "sentences": sentences[1:],
            "description": f"{title}. Daily AI & tech news. #AI #Tech #News",
            "tags": ["AI", "Tech News", "Artificial Intelligence", "Daily News", "Tech"],
        }

    @staticmethod
    def _clean_sentences(sentences: list[str]) -> list[str]:
        cleaned = []
        for s in sentences:
            s = (s or "").strip().strip('"').strip()
            if not s:
                continue
            if len(s) < 3 or all(ch in ".!?,—;:'\" " for ch in s):
                continue
            cleaned.append(s)
        return cleaned

    @staticmethod
    def _estimate_duration(sentence_count: int) -> int:
        return max(20, sentence_count * 7)
