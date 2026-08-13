"""Jarvis backend: JSON-RPC over stdio, spawned by the Electron app (or used standalone).

Protocol: newline-delimited JSON.
  Request : {"id": int, "method": str, "params": {...}}
  Response: {"id": int, "result": {...}} or {"id": int, "error": str}
  Event   : {"event": str, "data": {...}}
"""
from __future__ import annotations

import json
import sys
import threading
import traceback

from jarvis.orchestrator import Orchestrator


class Server:
    def __init__(self):
        self._lock = threading.Lock()
        self.orch = Orchestrator(emit=self.emit_event)

    def emit_event(self, event: str, data: dict) -> None:
        with self._lock:
            sys.stdout.write(json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def send(self, payload: dict) -> None:
        with self._lock:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def _dispatch(self, req: dict) -> None:
        mid, method, params = req.get("id"), req.get("method"), req.get("params") or {}

        def run() -> None:
            try:
                if method == "cancel":
                    self.orch.request_cancel()
                    result = {"cancelled": True}
                elif method == "run_pipeline":
                    result = self.orch.run_pipeline(params)
                elif method == "run_agent":
                    result = self.orch.run_agent(params.get("agent"), params)
                elif method == "get_status":
                    result = self.orch.status()
                elif method == "get_config":
                    result = self.orch.config_dict()
                elif method == "save_config":
                    result = self.orch.save_config(params.get("updates") or {})
                elif method == "list_outputs":
                    result = self.orch.list_outputs()
                elif method == "health":
                    result = {"ok": True}
                else:
                    raise ValueError(f"Unknown method: {method}")
                self.send({"id": mid, "ok": True, "result": result})
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc(file=sys.stderr)
                self.send({"id": mid, "ok": False, "error": str(exc)})

        threading.Thread(target=run, daemon=True).start()

    def serve(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._dispatch(req)


def main() -> None:
    server = Server()
    server.serve()


if __name__ == "__main__":
    main()
