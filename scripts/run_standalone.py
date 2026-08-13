#!/usr/bin/env python3
"""Run the Jarvis pipeline from the terminal (no Electron needed).

Usage:
    python3 scripts/run_standalone.py [--topic "GPT-5 release"] [--upload] [--schedule-hours 3]
    python3 scripts/run_standalone.py --agent script --topic "OpenAI news"
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))

from jarvis.orchestrator import Orchestrator  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Jarvis YouTube pipeline")
    parser.add_argument("--topic", default="", help="Optional specific topic (defaults to auto trend pick)")
    parser.add_argument("--upload", action="store_true", help="Upload the final video to YouTube")
    parser.add_argument("--schedule-hours", type=int, default=0, help="Schedule publishing N hours in the future")
    parser.add_argument("--format", choices=["vertical", "horizontal"], default=None)
    parser.add_argument("--agent", default=None, help="Run a single agent: trend|script|voice|video|thumbnail|upload")
    args = parser.parse_args()

    def emit(event: str, data: dict) -> None:
        print(f"\n<{event}>", data if event in ("pipeline_complete", "video_uploaded", "trend_selected") else "")

    orch = Orchestrator(emit=emit)
    params = {
        "topic": args.topic,
        "upload": args.upload,
        "schedule_hours": args.schedule_hours,
        "format": args.format,
    }
    if args.agent:
        orch.run_agent(args.agent, params)
        print("\nDone.")
        return
    result = orch.run_pipeline(params)
    print("\n=== Result ===")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
