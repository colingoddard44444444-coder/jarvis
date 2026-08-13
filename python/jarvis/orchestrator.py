"""Orchestrator: runs the multi-agent YouTube production pipeline."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Optional

from .agent import Agent, CancelError, new_run_id
from .config import Config, load_config, save_config

PIPELINE_ORDER = ["trend", "script", "voice", "video", "thumbnail", "upload"]


class Orchestrator:
    def __init__(self, emit: Callable[[str, dict], None], cfg_path: Optional[str] = None):
        self.emit = emit
        self.cfg = load_config(cfg_path)
        self.cancel = threading.Event()
        self.running = False
        self.current_run_id: Optional[str] = None
        self.agents: dict[str, Agent] = {}
        self._register_agents()

    def _register_agents(self) -> None:
        from .agents.trend import TrendAgent
        from .agents.script import ScriptAgent
        from .agents.voice import VoiceAgent
        from .agents.video import VideoAgent
        from .agents.thumbnail import ThumbnailAgent
        from .agents.upload import UploadAgent
        for cls in (TrendAgent, ScriptAgent, VoiceAgent, VideoAgent, ThumbnailAgent, UploadAgent):
            agent = cls()
            agent.orch = self
            self.agents[agent.name] = agent

    # --- logging / events ---------------------------------------------------
    def log(self, msg: str, level: str = "info") -> None:
        self.emit("log", {"level": level, "message": msg, "ts": time.time()})

    def progress(self, agent: str, stage: str, pct: float) -> None:
        self.emit("progress", {"agent": agent, "stage": stage, "pct": round(pct)})

    def request_cancel(self) -> None:
        self.cancel.set()
        self.log("Cancellation requested", "warn")

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise CancelError("cancelled")

    # --- pipeline -----------------------------------------------------------
    def run_pipeline(self, params: dict[str, Any] | None = None) -> dict:
        params = params or {}
        if self.running:
            raise RuntimeError("A pipeline is already running.")
        self.running = True
        self.cancel.clear()
        run_id = new_run_id()
        self.current_run_id = run_id
        workdir = os.path.join(self.cfg.output_dir(), run_id)
        os.makedirs(workdir, exist_ok=True)
        ctx: dict[str, Any] = {
            "workdir": workdir,
            "run_id": run_id,
            "topic": (params.get("topic") or "").strip(),
            "params": params,
        }
        self.log(f"=== Pipeline {run_id} started ===")
        results: dict[str, Any] = {}
        try:
            for name in PIPELINE_ORDER:
                if name == "upload" and not self._should_upload(params):
                    self.log("Skipping upload stage (auto_upload disabled).")
                    continue
                self.check_cancel()
                self.progress(name, "start", 0)
                self.emit("agent_started", {"agent": name, "run_id": run_id})
                agent = self.agents[name]
                res = agent.run(self, ctx)
                results[name] = res
                ctx[name] = res
                self.progress(name, "done", 100)
                self.emit("agent_done", {"agent": name, "ok": True, "run_id": run_id})
                self.check_cancel()
            self._write_metadata(ctx, results)
            self.log("=== Pipeline complete ===")
            summary = self._summary(ctx, results)
            self.emit("pipeline_complete", {"run_id": run_id, **summary})
            return summary
        except CancelError:
            self.log("Pipeline cancelled.", "warn")
            self.emit("pipeline_cancelled", {"run_id": run_id})
            return {"status": "cancelled"}
        except Exception as exc:
            self.log(f"Pipeline failed: {exc}", "error")
            self.emit("pipeline_failed", {"run_id": run_id, "error": str(exc)})
            raise
        finally:
            self.running = False
            self.current_run_id = None

    def _should_upload(self, params: dict[str, Any]) -> bool:
        if "upload" in params:
            return bool(params["upload"])
        return bool(self.cfg.get("channel", "auto_upload", default=False))

    def run_agent(self, name: str, params: dict[str, Any] | None = None) -> dict:
        params = params or {}
        if name not in self.agents:
            raise ValueError(f"Unknown agent: {name}. Available: {', '.join(self.agents)}")
        if self.running:
            raise RuntimeError("Pipeline is running. Cancel it first.")
        self.running = True
        self.cancel.clear()
        run_id = new_run_id()
        workdir = os.path.join(self.cfg.output_dir(), run_id)
        os.makedirs(workdir, exist_ok=True)
        ctx: dict[str, Any] = {"workdir": workdir, "run_id": run_id, "topic": params.get("topic", "").strip(), "params": params}
        try:
            self.emit("agent_started", {"agent": name, "run_id": run_id})
            res = self.agents[name].run(self, ctx)
            ctx[name] = res
            self.emit("agent_done", {"agent": name, "ok": True, "run_id": run_id})
            return {"run_id": run_id, "agent": name, "result": res}
        finally:
            self.running = False

    # --- persistence ---------------------------------------------------------
    def _write_metadata(self, ctx: dict, results: dict) -> None:
        script = results.get("script", {})
        voice = results.get("voice", {})
        video = results.get("video", {})
        trend = results.get("trend", {})
        meta = {
            "id": ctx["run_id"],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "topic": ctx.get("topic", ""),
            "trend": trend,
            "script": script,
            "voice": voice,
            "video": video,
            "thumbnail": results.get("thumbnail", {}).get("thumbnail"),
            "upload": results.get("upload", {}),
            # convenience (back-compat)
            "title": script.get("title"),
            "description": script.get("description"),
            "tags": script.get("tags", []),
            "sentences": voice.get("timings", []) or script.get("sentences", []),
            "narration": voice.get("narration"),
            "video_path": video.get("video"),
            "duration": video.get("duration") or voice.get("duration"),
            "youtube_id": results.get("upload", {}).get("video_id"),
            "sources": trend.get("story", {}).get("link", ""),
        }
        with open(os.path.join(ctx["workdir"], "metadata.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, ensure_ascii=False)

    def latest_metadata(self) -> Optional[dict]:
        out_dir = self.cfg.output_dir()
        if not os.path.isdir(out_dir):
            return None
        runs = sorted(
            (d for d in os.listdir(out_dir) if d.startswith("run_")),
            reverse=True,
        )
        for run in runs:
            path = os.path.join(out_dir, run, "metadata.json")
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as fh:
                        return json.load(fh)
                except (OSError, ValueError):
                    continue
        return None

    def _summary(self, ctx: dict, results: dict) -> dict:
        return {
            "run_id": ctx["run_id"],
            "topic": ctx.get("topic"),
            "title": results.get("script", {}).get("title"),
            "video": os.path.join(ctx["workdir"], "final.mp4"),
            "thumbnail": os.path.join(ctx["workdir"], "thumbnail.png"),
            "youtube_id": results.get("upload", {}).get("video_id"),
        }

    # --- RPC surface --------------------------------------------------------
    def status(self) -> dict:
        return {
            "running": self.running,
            "agents": {
                name: {
                    "name": agent.name,
                    "class": agent.__class__.__name__,
                    "description": agent.__doc__ or "",
                }
                for name, agent in self.agents.items()
            },
            "output_dir": self.cfg.output_dir(),
            "backend_version": "jarvis-0.1.0",
        }

    def config_dict(self) -> dict:
        return self.cfg.to_dict()

    def save_config(self, updates: dict[str, Any]) -> dict:
        save_config(self.cfg, updates)
        return self.config_dict()

    def list_outputs(self) -> list[dict]:
        out_dir = self.cfg.output_dir()
        outputs = []
        if os.path.isdir(out_dir):
            for run in sorted(os.listdir(out_dir), reverse=True):
                path = os.path.join(out_dir, run)
                if not os.path.isdir(path):
                    continue
                meta_path = os.path.join(path, "metadata.json")
                meta = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, encoding="utf-8") as fh:
                            meta = json.load(fh)
                    except (OSError, ValueError):
                        pass
                outputs.append({
                    "run_id": run,
                    "path": path,
                    "title": meta.get("title"),
                    "youtube_id": meta.get("youtube_id"),
                    "created_at": meta.get("created_at"),
                    "has_video": os.path.exists(os.path.join(path, "final.mp4")),
                    "has_thumbnail": os.path.exists(os.path.join(path, "thumbnail.png")),
                })
        return outputs
