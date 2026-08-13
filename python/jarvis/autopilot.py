"""Autopilot: schedules full-pipeline runs so the channel produces videos on its own."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class Autopilot:
    """A daemon loop that runs the production pipeline on an interval.

    Guards:
      - never starts while the orchestrator is already running a pipeline
      - enforces a daily cap (autopilot.max_per_day)
    """

    def __init__(self, orch, emit: Callable[[str, dict], None]):
        self.orch = orch
        self.emit = emit
        self.thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.runs_today = 0
        self._day = ""
        self.last_run_at: Optional[str] = None
        self.last_result: Optional[str] = None
        self.next_run_at: Optional[str] = None

    # --- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self._event("started")

    def stop(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=3)
        self.thread = None
        self._event("stopped")

    # --- status --------------------------------------------------------------
    def status(self) -> dict:
        return {
            "enabled": bool(self.thread and self.thread.is_alive()),
            "interval_hours": self.orch.cfg.get("autopilot", "interval_hours", default=6),
            "max_per_day": self.orch.cfg.get("autopilot", "max_per_day", default=8),
            "upload": bool(self.orch.cfg.get("autopilot", "upload", default=False)),
            "format": self.orch.cfg.get("autopilot", "format", default="vertical"),
            "runs_today": self.runs_today,
            "last_run_at": self.last_run_at,
            "last_result": self.last_result,
            "next_run_at": self.next_run_at,
            "output_dir": self.orch.cfg.output_dir(),
        }

    # --- internals ------------------------------------------------------------
    def _interval_seconds(self) -> float:
        hours = float(self.orch.cfg.get("autopilot", "interval_hours", default=6) or 6)
        return max(60.0, hours * 3600)

    def _maxed_out(self) -> bool:
        today = time.strftime("%Y%m%d")
        if self._day != today:
            self._day = today
            self.runs_today = 0
        limit = int(self.orch.cfg.get("autopilot", "max_per_day", default=8) or 1)
        return self.runs_today >= limit

    def _loop(self) -> None:
        self._log("Autopilot engaged. Next run in %.1f h." % (self._interval_seconds() / 3600))
        self.next_run_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + self._interval_seconds()))
        while not self._stop.wait(self._interval_seconds()):
            if self.orch.running:
                self._log("Pipeline busy — skipping this cycle.")
                continue
            if self._maxed_out():
                self._log("Daily limit reached — waiting for tomorrow.")
                self.next_run_at = time.strftime("%Y-%m-%d 00:00")
                continue
            self._run()
            self.next_run_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + self._interval_seconds()))
        self._log("Autopilot disengaged.")

    def _run(self) -> None:
        self.runs_today += 1
        self.last_run_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        fmt = self.orch.cfg.get("autopilot", "format", default="vertical")
        upload = bool(self.orch.cfg.get("autopilot", "upload", default=False))
        if not upload:
            upload = bool(self.orch.cfg.get("channel", "auto_upload", default=False))
        topic = (self.orch.cfg.get("autopilot", "topic", default="") or "").strip()
        params = {"topic": topic, "format": fmt, "upload": upload, "autopilot": True}
        self._event("run_started", params=params)
        try:
            res = self.orch.run_pipeline(params)
            self.last_result = "ok" if res.get("status") != "cancelled" else "cancelled"
            self._event("run_done", result=res)
        except Exception as exc:  # noqa: BLE001
            self.last_result = f"error: {exc}"
            self._event("run_error", error=str(exc))

    def _event(self, type_: str, **data) -> None:
        self.emit("autopilot_event", {"type": type_, **data})

    def _log(self, msg: str) -> None:
        self.emit("log", {"level": "info", "message": f"[autopilot] {msg}", "ts": time.time()})
