"""Agent base classes and shared utilities."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Callable, Optional

from .config import Config


class CancelError(RuntimeError):
    pass


class Agent:
    name = "base"

    def __init__(self):
        self.orch: Optional["Orchestrator"] = None

    def run(self, orch, ctx: dict) -> dict:
        raise NotImplementedError

    # --- helpers -----------------------------------------------------------
    def log(self, msg: str, level: str = "info") -> None:
        if self.orch:
            self.orch.log(f"[{self.name}] {msg}", level)

    def progress(self, stage: str, pct: float) -> None:
        if self.orch:
            self.orch.emit("progress", {"agent": self.name, "stage": stage, "pct": round(pct)})

    def check_cancel(self) -> None:
        if self.orch and self.orch.cancel.is_set():
            raise CancelError("cancelled")

    def artifact(self, ctx: dict, key: str, required: bool = True):
        val = ctx.get(key)
        if val is None:
            meta = self._latest_metadata()
            if meta:
                val = meta.get(key)
        if val is None and required:
            raise RuntimeError(f"Missing artifact '{key}'. Run the full pipeline or the {key} stage first.")
        return val

    def _latest_metadata(self) -> Optional[dict]:
        if not self.orch:
            return None
        return self.orch.latest_metadata()

    def meta_path(self, ctx: dict) -> str:
        return os.path.join(ctx["workdir"], "metadata.json")


def ensure_tools(required: list[str]) -> None:
    missing = []
    for tool in required:
        try:
            subprocess.run([tool, "-version"], capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            missing.append(tool)
    if missing:
        raise RuntimeError(
            f"Missing system tools: {', '.join(missing)}. "
            "Run scripts/setup_popos.sh to install them."
        )


def probe_duration(path: str) -> float:
    ensure_tools(["ffprobe"])
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float(out.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Could not read duration of {path}: {out.stderr[:200]}") from exc


def run_cmd(cmd: list[str], log: Callable[[str], None], cwd: Optional[str] = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    log("$ " + " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        raise RuntimeError(f"Command failed ({' '.join(cmd)}): {tail}")
    return proc


def new_run_id() -> str:
    return time.strftime("run_%Y%m%d_%H%M%S")
