#!/usr/bin/env python3
"""One-time YouTube OAuth setup.

Prereq: Google Cloud project with YouTube Data API v3 enabled, and an OAuth
client (Desktop app) JSON downloaded to config/client_secret.json.

Usage:
    python3 scripts/oauth_google.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from jarvis.config import load_config  # noqa: E402

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main() -> None:
    cfg = load_config()
    secrets_path = cfg.abs(cfg.get("youtube", "client_secrets", default="config/client_secret.json"))
    token_path = cfg.abs(cfg.get("youtube", "token_path", default="config/youtube_token.json"))

    if not os.path.exists(secrets_path):
        sys.exit(
            f"client_secrets not found at {secrets_path}\n\n"
            "Steps:\n"
            "1. Go to https://console.cloud.google.com/apis/credentials\n"
            "2. Create OAuth client ID -> Desktop app\n"
            "3. Download JSON and save it as config/client_secret.json\n"
            "4. Make sure 'YouTube Data API v3' is enabled for the project."
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(token_path):
        with open(token_path, encoding="utf-8") as fh:
            creds = Credentials.from_authorized_user_info(json.load(fh), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
        try:
            creds = flow.run_local_server(port=0, open_browser=True)
        except Exception:
            print("\nBrowser flow unavailable — using manual code flow.")
            creds = flow.run_console()

        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())
        print(f"\nSaved credentials to {token_path}")

    yt = build("youtube", "v3", credentials=creds)
    resp = yt.channels().list(part="snippet", mine=True).execute()
    channel = resp["items"][0]["snippet"]
    print(f"Authorized as: {channel['title']}")
    print("Ready to upload.")


if __name__ == "__main__":
    main()
