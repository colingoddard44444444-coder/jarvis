"""Agent 6/6 — Uploader: publishes to YouTube via the Data API v3 (OAuth)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from ..agent import Agent


class UploadAgent(Agent):
    """Uploads final.mp4 with title/description/tags, optionally scheduled in the future."""

    name = "upload"

    def run(self, orch, ctx: dict) -> dict:
        script = ctx.get("script") or self.artifact(ctx, "script")
        video = ctx.get("video") or self.artifact(ctx, "video")
        video_path = video.get("video") if isinstance(video, dict) else video
        if not video_path or not os.path.exists(video_path):
            raise RuntimeError(f"Video file not found: {video_path}")

        cfg = orch.cfg
        token_path = cfg.abs(cfg.get("youtube", "token_path", default="config/youtube_token.json"))
        if not os.path.exists(token_path):
            msg = (
                "YouTube is not authorized yet.\n"
                "1) Put your Google OAuth client JSON at config/client_secret.json\n"
                "2) Run: python3 scripts/oauth_google.py\n"
                "3) Re-run this upload."
            )
            orch.emit("auth_required", {"message": msg, "token_path": token_path})
            raise RuntimeError("YouTube OAuth token missing. See the auth_required message.")

        params = ctx.get("params", {})
        schedule_hours = int(params.get("schedule_hours", cfg.get("channel", "publish_in_future_hours", default=0)) or 0)
        title = script.get("title", "Daily AI News")
        if schedule_hours > 0:
            title += f" ({datetime.now().strftime('%b %d')})"

        body = {
            "snippet": {
                "title": title,
                "description": script.get("description", ""),
                "tags": script.get("tags", [])[:20],
                "categoryId": str(cfg.get("youtube", "category_id", default="28")),
                "defaultLanguage": cfg.get("channel", "language", default="en"),
            },
            "status": {
                "privacyStatus": "private",
                "selfDeclaredMadeForKids": False,
                "embeddable": True,
            },
        }
        publish_at = None
        if schedule_hours > 0:
            publish_at = (datetime.now(timezone.utc) + timedelta(hours=schedule_hours)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            body["status"]["publishAt"] = publish_at

        self.log(f"Uploading '{title}' to YouTube" + (f" (scheduled {publish_at})" if publish_at else ""))
        service = self._service(token_path)
        media = self._media_file(video_path)
        req = service.videos().insert(part="snippet,status", body=body, media_body=media)
        self.progress("uploading", 10)
        response = req.execute()
        video_id = response["id"]
        self.log(f"Uploaded! Video ID: {video_id} — https://youtu.be/{video_id}")
        self.progress("done", 100)
        orch.emit("video_uploaded", {"video_id": video_id, "url": f"https://youtu.be/{video_id}"})
        return {"video_id": video_id, "url": f"https://youtu.be/{video_id}"}

    def _service(self, token_path: str):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        import json
        with open(token_path, encoding="utf-8") as fh:
            token = json.load(fh)
        creds = Credentials(
            token=token["token"],
            refresh_token=token.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=token["client_id"],
            client_secret=token["client_secret"],
        )
        return build("youtube", "v3", credentials=creds)

    def _media_file(self, path: str):
        from googleapiclient.http import MediaFileUpload
        return MediaFileUpload(path, chunksize=256 * 1024 * 1024, resumable=True)
