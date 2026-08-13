"""Agent 5/6 — Thumbnail: generates a 1280x720 click-worthy thumbnail."""
from __future__ import annotations

import os

from .. import media
from ..agent import Agent


class ThumbnailAgent(Agent):
    """Renders the video thumbnail with the optimized title."""

    name = "thumbnail"

    def run(self, orch, ctx: dict) -> dict:
        script = ctx.get("script") or self.artifact(ctx, "script")
        title = script.get("title", "AI News")
        subtitle = script.get("hook", "")[:28]
        channel = orch.cfg.get("channel", "channel_name", default="AI Pulse Daily")
        out = os.path.join(ctx["workdir"], "thumbnail.png")
        media.make_thumbnail(title, subtitle, channel).save(out)
        self.log(f"Thumbnail ready: {out}")
        return {"thumbnail": out}
