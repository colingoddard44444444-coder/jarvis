#!/usr/bin/env python3
"""Jarvis mobile web control panel — run the whole factory from your phone.

Usage:
    python3 python/web_server.py [port]

Then open http://<this-device-ip>:8077 in your phone's browser. Voice control
uses the browser's own speech recognition (no vosk needed on the phone).
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))

from jarvis.autopilot import Autopilot  # noqa: E402
from jarvis.orchestrator import Orchestrator  # noqa: E402
from jarvis.voice import CommandParser  # noqa: E402

PORT = 8077


class Broadcaster:
    """Fan log/progress events out to every connected SSE client."""

    def __init__(self):
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()

    def emit(self, event: str, data: dict) -> None:
        payload = (json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n\n").encode()
        with self._lock:
            dead = []
            for q in self._clients:
                try:
                    q.put_nowait(payload)
                except Exception:  # noqa: BLE001
                    dead.append(q)
            for q in dead:
                self._clients.remove(q)

    def register(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._clients.append(q)
        return q

    def unregister(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)


def lan_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return ips


class JarvisApp:
    def __init__(self):
        self.broadcast = Broadcaster()
        self.orch = Orchestrator(emit=self.broadcast.emit)
        self.autopilot = Autopilot(self.orch, emit=self.broadcast.emit)
        self.parser = CommandParser()
        if self.orch.cfg.get("autopilot", "enabled", default=False):
            self.autopilot.start()

    # --- actions shared with the voice dispatcher ---------------------------
    def run_pipeline(self, topic: str, vfmt: str = "", style: str = "") -> str:
        if self.orch.running:
            return "A pipeline is already running."
        params = {
            "topic": topic,
            "format": vfmt or self.orch.cfg.get("video", "format", default="vertical"),
            "upload": bool(self.orch.cfg.get("channel", "auto_upload", default=False)),
        }
        if style:
            params["style"] = style
        self.broadcast.emit("log", {"level": "warn", "message": "Pipeline starting from phone…", "ts": time.time()})
        threading.Thread(target=self._safe_pipeline, args=(params,), daemon=True).start()
        topic_txt = topic or "today's top trend"
        return f"Starting production on {topic_txt}."

    def _safe_pipeline(self, params: dict) -> None:
        try:
            self.orch.run_pipeline(params)
        except Exception as exc:  # noqa: BLE001
            self.broadcast.emit("log", {"level": "error", "message": f"Pipeline failed: {exc}", "ts": time.time()})

    def upload(self) -> str:
        if self.orch.running:
            return "The pipeline is busy."
        threading.Thread(target=self._safe_upload, daemon=True).start()
        return "Uploading the latest video to YouTube."

    def _safe_upload(self) -> None:
        try:
            self.orch.run_agent("upload", {"upload": True})
        except Exception as exc:  # noqa: BLE001
            self.broadcast.emit("log", {"level": "error", "message": f"Upload failed: {exc}", "ts": time.time()})

    def status_text(self) -> str:
        meta = self.orch.latest_metadata()
        parts = [f"{len(self.orch.agents)} agents online."]
        if self.orch.running:
            parts.append("A pipeline is currently running.")
        elif meta and meta.get("title"):
            parts.append(f"Latest video: {meta['title']}.")
        else:
            parts.append("No videos produced yet.")
        if self.autopilot.status().get("enabled"):
            parts.append("Autopilot is engaged.")
        return " ".join(parts)

    def handle_voice(self, text: str) -> str:
        parsed = self.parser.parse(text)
        if not parsed:
            reply = "I didn't catch that. Try: make a video about AI, or upload to YouTube."
            self.broadcast.emit("voice_event", {"type": "reply", "text": reply})
            return reply
        action, params = parsed
        self.broadcast.emit("voice_event", {"type": "action", "action": action, "params": params})
        if action == "pipeline":
            reply = self.run_pipeline(params.get("topic", ""))
        elif action == "upload":
            reply = self.upload()
        elif action == "cancel":
            self.orch.request_cancel()
            reply = "Cancelling production."
        elif action == "status":
            reply = self.status_text()
        elif action == "autopilot_on":
            self.autopilot.start()
            reply = "Autopilot engaged. I'll keep producing videos automatically."
        elif action == "autopilot_off":
            self.autopilot.stop()
            reply = "Autopilot disengaged."
        elif action == "greeting":
            reply = "At your service. Say make a video to begin production."
        else:
            reply = "Command understood."
        self.broadcast.emit("voice_event", {"type": "reply", "text": reply})
        return reply


app = JarvisApp()


def _json(handler, obj: dict, code: int = 200) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw)
    except ValueError:
        return {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "JarvisMobile"

    def log_message(self, *a):  # silence
        pass

    # --- routes -------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._page()
        elif path == "/api/status":
            _json(self, {"ok": True, "orch": app.orch.status(), "autopilot": app.autopilot.status(),
                         "ips": lan_ips(), "port": PORT, "ts": time.time()})
        elif path == "/api/outputs":
            _json(self, {"ok": True, "outputs": app.orch.list_outputs()})
        elif path == "/api/autopilot":
            _json(self, app.autopilot.status())
        elif path == "/api/events":
            self._sse()
        elif path.startswith("/media/"):
            self._media(path)
        else:
            _json(self, {"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = _read_json(self)
        if path == "/api/run":
            _json(self, {"ok": True, "message": app.run_pipeline(data.get("topic", ""), data.get("format", ""), data.get("style", ""))})
        elif path == "/api/cancel":
            app.orch.request_cancel()
            _json(self, {"ok": True, "message": "Cancelling."})
        elif path == "/api/upload":
            _json(self, {"ok": True, "message": app.upload()})
        elif path == "/api/autopilot":
            if data.get("enabled"):
                app.autopilot.start()
            else:
                app.autopilot.stop()
            _json(self, app.autopilot.status())
        elif path == "/api/voice":
            _json(self, {"ok": True, "reply": app.handle_voice(data.get("text", "")), "heard": data.get("text", "")})
        else:
            _json(self, {"ok": False, "error": "not found"}, 404)

    # --- pages ---------------------------------------------------------------
    def _page(self):
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _sse(self):
        q = app.broadcast.register()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                payload = q.get(timeout=15)
                self.wfile.write(b"data: " + payload)
                self.wfile.flush()
        except Exception:  # noqa: BLE001 - client disconnected
            pass
        finally:
            app.broadcast.unregister(q)

    def _media(self, path):
        rel = path[len("/media/"):]
        if rel in ("", ".") or ".." in rel.split("/"):
            _json(self, {"ok": False, "error": "bad path"}, 404)
            return
        full = os.path.realpath(os.path.join(app.orch.cfg.output_dir(), rel))
        base = os.path.realpath(app.orch.cfg.output_dir())
        if not full.startswith(base + os.sep) or not os.path.isfile(full):
            _json(self, {"ok": False, "error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(full, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
<title>JARVIS</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
  body{background:#04070d;color:#d8f6ec;font-family:"Roboto Mono","DejaVu Sans Mono",monospace;min-height:100vh;
    background:radial-gradient(900px 500px at 80% -10%,rgba(0,224,160,.10),transparent 60%),#04070d}
  body::before{content:"";position:fixed;inset:0;pointer-events:none;background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px);opacity:.4}
  .wrap{max-width:520px;margin:0 auto;padding:14px}
  header{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid rgba(0,224,160,.3);margin-bottom:14px}
  .brand{font-size:20px;font-weight:800;letter-spacing:5px;color:#eafff7;text-shadow:0 0 12px rgba(0,224,160,.8)}
  .dot{width:10px;height:10px;border-radius:50%;background:#00e0a0;box-shadow:0 0 14px #00e0a0;animation:pulse 2s infinite}
  @keyframes pulse{50%{opacity:.35}}
  .pill{font-size:10px;letter-spacing:1px;padding:4px 8px;border:1px solid rgba(0,224,160,.3);color:#5f9082}
  .pill.on{color:#ffbe5a;border-color:#ffbe5a}
  .pill.ok{color:#00e0a0;border-color:#00e0a0}
  .panel{position:relative;border:1px solid rgba(0,224,160,.25);background:rgba(6,14,22,.9);padding:14px;margin-bottom:14px}
  .panel::before,.panel::after{content:"";position:absolute;width:12px;height:12px;pointer-events:none}
  .panel::before{top:-1px;left:-1px;border-top:2px solid #00e0a0;border-left:2px solid #00e0a0}
  .panel::after{bottom:-1px;right:-1px;border-bottom:2px solid #00e0a0;border-right:2px solid #00e0a0}
  h2{font-size:12px;letter-spacing:2px;color:#00e0a0;text-transform:uppercase;margin-bottom:10px}
  h2::before{content:"▸ "}
  label{display:block;font-size:10px;letter-spacing:1px;color:#5f9082;margin:8px 0 4px}
  input,select{width:100%;background:#08131e;color:#d8f6ec;border:1px solid rgba(0,224,160,.25);padding:11px;font-size:15px;font-family:inherit;outline:none}
  .row{display:flex;gap:10px;margin-top:10px}
  .row>*{flex:1}
  button{border:1px solid rgba(0,224,160,.35);background:#08131e;color:#d8f6ec;padding:12px;font-size:14px;font-family:inherit;font-weight:700;letter-spacing:1px;cursor:pointer}
  button:active{transform:scale(.97)}
  .primary{background:rgba(0,224,160,.15);border-color:#00e0a0;color:#eafff7}
  .danger{border-color:#ff5d5d;color:#ff5d5d}
  .ghost{padding:8px;font-size:11px}
  #mic{width:100%;padding:22px;font-size:16px;letter-spacing:4px;border-color:#00e0a0;color:#eafff7;background:rgba(0,224,160,.08)}
  #mic.rec{border-color:#ff5d5d;color:#ff5d5d;animation:pulse 1s infinite}
  #transcript{min-height:40px;margin-top:10px;padding:10px;border:1px dashed rgba(0,224,160,.3);font-size:12px;color:#5f9082}
  #console{background:#03070c;border:1px solid rgba(0,224,160,.25);padding:10px;font-size:11px;line-height:1.6;height:30vh;overflow-y:auto}
  .info{color:#d8f6ec}.warn{color:#ffbe5a}.error{color:#ff5d5d}.success{color:#00e0a0}
  .muted{color:#5f9082;font-size:10px;letter-spacing:1px}
  .out{display:flex;justify-content:space-between;align-items:center;padding:8px;border:1px solid rgba(0,224,160,.2);margin-bottom:6px;font-size:12px}
  .out a{color:#00e0a0;text-decoration:none}
  .statusbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="dot"></span><span class="brand">JARVIS</span>
    <span style="flex:1"></span>
    <span id="pill" class="pill">offline</span>
  </header>

  <div class="panel">
    <div class="statusbar">
      <span id="st-run" class="muted">idle</span>
      <span id="st-ap" class="muted">autopilot off</span>
      <span id="st-out" class="muted" style="flex:1;text-align:right"></span>
    </div>
    <h2>Voice Control</h2>
    <button id="mic">TAP &amp; SPEAK</button>
    <div id="transcript">Tap and speak. Example: "make a video about AI".</div>
  </div>

  <div class="panel">
    <h2>New Video</h2>
    <label for="topic">Topic (empty = auto-pick today's trend)</label>
    <input id="topic" placeholder="e.g. OpenAI releases GPT-5…"/>
    <div class="row">
      <div><label for="fmt">Format</label>
        <select id="fmt"><option value="vertical">Vertical</option><option value="horizontal">Horizontal</option></select>
      </div>
      <div><label for="style">Style</label>
        <select id="style"><option value="jarvis">JARVIS HUD</option><option value="tech">Tech Neon</option></select>
      </div>
    </div>
    <div class="row">
      <button id="run" class="primary">▶ RUN</button>
      <button id="cancel" class="danger">CANCEL</button>
    </div>
  </div>

  <div class="panel">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h2 style="margin:0">Autopilot</h2>
      <button id="ap" class="ghost">ENABLE</button>
    </div>
    <div id="ap-status" class="muted" style="margin-top:8px">Autopilot off.</div>
  </div>

  <div class="panel">
    <h2>Console</h2>
    <div id="console"></div>
  </div>

  <div class="panel">
    <h2>Outputs</h2>
    <div id="outputs"><div class="muted">Loading…</div></div>
  </div>
</div>

<script>
var $=function(id){return document.getElementById(id)};
var rec=null;
function log(msg,lvl){
  var c=$("console"),d=document.createElement("div");
  d.className=lvl||"info";d.textContent="["+new Date().toLocaleTimeString()+"] "+msg;
  c.appendChild(d);while(c.children.length>300)c.removeChild(c.firstChild);c.scrollTop=c.scrollHeight;
}
function speak(text){
  try{var u=new SpeechSynthesisUtterance(text);u.lang="en-US";speechSynthesis.cancel();speechSynthesis.speak(u);}catch(e){}
}
function pill(el,cls,t){el.className="pill "+cls;el.textContent=t;}
function api(path,method,body){
  return fetch(path,{method:method||"GET",headers:body?{"Content-Type":"application/json"}:{},body:body?JSON.stringify(body):null}).then(function(r){return r.json()});
}
function refreshStatus(){
  api("/api/status").then(function(s){
    pill($("pill"), s.ok&&s.autopilot.enabled?"on":"ok", s.ok?"ONLINE":"offline");
    $("st-run").textContent = s.orch&&s.orch.running?"RUNNING":"idle";
    $("st-ap").textContent = s.autopilot&&s.autopilot.enabled?("AUTOPILOT: ON · next "+s.autopilot.next_run_at):"autopilot off";
  });
  api("/api/outputs").then(function(r){
    var b=$("outputs");b.innerHTML="";
    var outs=(r.outputs||[]);
    if(!outs.length){b.innerHTML='<div class="muted">No videos yet.</div>';return;}
    outs.forEach(function(o){
      var d=document.createElement("div");d.className="out";
      var m=document.createElement("span");m.textContent=(o.title||o.run_id).slice(0,34);
      d.appendChild(m);
      var row=document.createElement("span");
      if(o.has_video){var a=document.createElement("a");a.href="/media/"+o.run_id+"/final.mp4";a.target="_blank";a.textContent="watch ";row.appendChild(a);}
      if(o.youtube_id){var y=document.createElement("a");y.href="https://youtu.be/"+o.youtube_id;y.target="_blank";y.textContent="youtu.be";row.appendChild(y);}
      d.appendChild(row);b.appendChild(d);
    });
  });
}
function startRec(){
  var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){$("transcript").textContent="Speech recognition not supported in this browser.";return;}
  if(rec)rec.abort();
  rec=new SR();rec.lang="en-US";rec.interimResults=false;rec.maxAlternatives=1;
  var btn=$("mic");btn.classList.add("rec");btn.textContent="LISTENING…";
  $("transcript").textContent="Listening…";
  rec.onresult=function(e){
    var t=e.results[0][0].transcript;
    $("transcript").textContent='You said: "'+t+'"';
    btn.classList.remove("rec");btn.textContent="TAP & SPEAK";
    api("/api/voice", "POST", {text:t}).then(function(r){
      log('Voice: "'+r.heard+'"','warn');
      $("transcript").textContent='Jarvis: "'+(r.reply||"")+'"';
      speak(r.reply);
    });
  };
  rec.onend=function(){btn.classList.remove("rec");btn.textContent="TAP & SPEAK";};
  rec.onerror=function(ev){btn.classList.remove("rec");btn.textContent="TAP & SPEAK";$("transcript").textContent="Mic error: "+ev.error;};
  rec.start();
}
$("mic").onclick=startRec;
$("run").onclick=function(){
  api("/api/run","POST",{topic:$("topic").value,format:$("fmt").value,style:$("style").value}).then(function(r){log(r.message,"warn");});
};
$("cancel").onclick=function(){api("/api/cancel","POST",{}).then(function(r){log(r.message,"warn");});};
$("ap").onclick=function(){
  var on=$("ap").textContent!=="DISABLE";
  api("/api/autopilot","POST",{enabled:on}).then(function(s){
    $("ap").textContent=s.enabled?"DISABLE":"ENABLE";
    $("st-ap").textContent=s.enabled?("AUTOPILOT: ON · next "+s.next_run_at):"autopilot off";
    log(s.enabled?"Autopilot engaged.":"Autopilot disengaged.", s.enabled?"success":"warn");
  });
};
function connectEvents(){
  var es=new EventSource("/api/events");
  es.onmessage=function(e){
    try{var m=JSON.parse(e.data);}catch(err){return;}
    switch(m.event){
      case "log": log(m.data.message, m.data.level); break;
      case "progress": break;
      case "agent_started": log("agent: "+m.data.agent,"warn"); break;
      case "agent_done": log("agent done: "+m.data.agent, m.data.ok?"success":"error"); break;
      case "pipeline_complete": log("✓ Video ready: "+(m.data.title||""),"success"); $("st-run").textContent="idle"; refreshStatus(); break;
      case "pipeline_failed": log("Pipeline failed: "+m.data.error,"error"); $("st-run").textContent="idle"; break;
      case "pipeline_cancelled": log("Pipeline cancelled.","warn"); $("st-run").textContent="idle"; break;
      case "video_uploaded": log("Published: "+m.data.url,"success"); refreshStatus(); break;
      case "autopilot_event": if(m.data.type==="run_started"){$("st-run").textContent="RUNNING";} break;
      case "trend_selected": log("Trend: "+m.data.title); break;
    }
  };
  es.onerror=function(){setTimeout(connectEvents,2000);};
}
refreshStatus();setInterval(refreshStatus,15000);connectEvents();
</script>
</body>
</html>
"""


def main() -> None:
    global PORT
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    print("=" * 52, flush=True)
    print("JARVIS mobile control panel", flush=True)
    for ip in lan_ips():
        print(f"  On this phone:  http://127.0.0.1:{port}", flush=True)
        print(f"  On your network:http://{ip}:{port}", flush=True)
    print(f"Output dir: {app.orch.cfg.output_dir()}", flush=True)
    print("=" * 52, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
