"""Agent 1/6 — Trend Research: picks today's hottest AI/tech story."""
from __future__ import annotations

from ..agent import Agent
from .. import trends


class TrendAgent(Agent):
    """Scans AI/tech RSS feeds, then checks YouTube traction to pick the trendiest story."""

    name = "trend"

    def run(self, orch, ctx: dict) -> dict:
        self.log("Fetching AI & tech news feeds...")
        stories = trends.fetch_stories(orch.cfg, limit=12)
        self.log(f"Found {len(stories)} candidate stories.")
        for i, s in enumerate(stories[:5], 1):
            self.log(f"  {i}. [{s['hours_ago']}h ago, score {s['score']}] {s['title']}")
        self.check_cancel()

        self.log("Checking YouTube traction for top stories...")
        story = trends.pick_topic(orch.cfg, stories)
        traction = story.get("traction") or {}
        self.log(f"Selected: {story['title']}")
        self.log(f"  Source: {story['link']} | median YT views: {traction.get('median_views', 'n/a')}")

        self.check_cancel()
        self.log("Fetching extra context for the writer...")
        extra = trends.find_extra_facts(story["title"])
        story["extra"] = extra
        orch.emit("trend_selected", {"title": story["title"], "link": story["link"]})
        return {"story": story}
