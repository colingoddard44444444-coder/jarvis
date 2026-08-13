"""Voice control: speech-to-text (vosk / Whisper), JARVIS voice replies, command parsing.

Mic capture uses system tools (ffmpeg -> arecord -> sox) so no native audio
libraries are required on Pop!_OS. Recognition is optional: if vosk is missing
or the model can't be downloaded, voice commands degrade gracefully to a
"mic offline" message while the rest of Jarvis keeps working.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable, Optional

try:
    from vosk import Model, KaldiRecognizer  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    Model = KaldiRecognizer = None

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
VOSK_DIR_NAME = "vosk-model-small-en-us-0.15"

# (action, params) pairs built from a spoken phrase.
PIPELINE_RE = re.compile(
    r"(?:make|create|generate|produce|start|run).{0,24}"
    r"(?:a |an |the )?(?:video|short|clip|episode|film|pipeline)(?: about| on| for| covering| of)?(?P<topic>.+)?",
    re.IGNORECASE,
)
UPLOAD_RE = re.compile(
    r"(?:upload|post|publish)(?: (?:the|it))?(?: (?:video|short|clip|one))?(?: to)? youtube|"
    r"(?:upload|post|publish) the (?:video|short|clip)",
    re.IGNORECASE,
)
CANCEL_RE = re.compile(r"\b(cancel|abort|stop|halt)\b", re.IGNORECASE)
STATUS_RE = re.compile(
    r"\b(status|how (?:are|is) (?:you|it)(?: going)?|what.s up|are you there|what can you do)\b",
    re.IGNORECASE,
)
AUTOPILOT_ON_RE = re.compile(r"(turn|switch)?\s*(on|engage|activate|start)( the)? (autopilot|autonomous)", re.IGNORECASE)
AUTOPILOT_OFF_RE = re.compile(r"(turn|switch)?\s*(off|disengage|deactivate|stop)( the)? (autopilot|autonomous)", re.IGNORECASE)
GREETING_RE = re.compile(r"^(hello|hi|hey|yo|good (morning|afternoon|evening))[,.!]*$", re.IGNORECASE)
MAKE_ANY_RE = re.compile(r"(make|create|generate|produce|start|run).{0,24}(video|short|clip|episode|film|pipeline)", re.IGNORECASE)


class CommandParser:
    """Maps a transcript to a (action, params) pair."""

    @staticmethod
    def parse(text: str) -> Optional[tuple[str, dict]]:
        t = text.strip()
        if not t:
            return None
        m = AUTOPILOT_ON_RE.search(t)
        if m:
            return ("autopilot_on", {})
        m = AUTOPILOT_OFF_RE.search(t)
        if m:
            return ("autopilot_off", {})
        if CANCEL_RE.search(t) and not UPLOAD_RE.search(t):
            return ("cancel", {})
        if UPLOAD_RE.search(t):
            return ("upload", {})
        if STATUS_RE.search(t):
            return ("status", {})
        m = PIPELINE_RE.search(t)
        if m:
            topic = (m.group("topic") or "").strip()
            if topic.startswith(("about ", "on ", "for ", "covering ")):
                topic = topic.split(" ", 1)[1].strip()
            return ("pipeline", {"topic": topic})
        if MAKE_ANY_RE.search(t):
            return ("pipeline", {"topic": ""})
        if GREETING_RE.match(t):
            return ("greeting", {})
        return None


def _tmp_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "jarvis_voice")
    os.makedirs(d, exist_ok=True)
    return d


def find_recorder() -> Optional[str]:
    """Return the best available mic recorder name, or None."""
    for tool in ("arecord", "sox", "ffmpeg"):
        if shutil.which(tool):
            return tool
    return None


def find_player() -> Optional[str]:
    for tool in ("ffplay", "aplay", "paplay"):
        if shutil.which(tool):
            return tool
    return None


def _recorder_cmd(recorder: str, raw_path: str) -> list[str]:
    """Command that records raw s16le 16kHz mono PCM until killed."""
    if recorder == "arecord":
        return ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", raw_path]
    if recorder == "ffmpeg":
        return ["ffmpeg", "-y", "-loglevel", "error", "-f", "pulse", "-i", "default",
                "-ar", "16000", "-ac", "1", "-f", "s16le", raw_path]
    return ["sox", "-d", "-r", "16000", "-c", "1", "-b", "16", "-e", "signed-integer", raw_path]


def _wrap_raw(raw_path: str, wav_path: str) -> bool:
    """Wrap a raw PCM stream into a valid WAV so partial captures are readable."""
    if not os.path.exists(raw_path) or os.path.getsize(raw_path) < 1000:
        return False
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "16000", "-ac", "1",
             "-i", raw_path, "-c", "pcm_s16le", wav_path],
            capture_output=True, timeout=60,
        )
        return os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class CaptureSession:
    """Records raw PCM until stop() is called, then wraps it into a valid WAV."""

    def __init__(self, recorder: str):
        self.recorder = recorder
        self.proc: Optional[subprocess.Popen] = None
        self.raw_path: Optional[str] = None
        self.wav_path: Optional[str] = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self.proc:
                return True
            self.raw_path = os.path.join(_tmp_dir(), f"cap_{int(time.time() * 1000)}.raw")
            self.wav_path = self.raw_path.replace(".raw", ".wav")
            try:
                self.proc = subprocess.Popen(
                    _recorder_cmd(self.recorder, self.raw_path),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (FileNotFoundError, OSError):
                self.proc = None
                return False
            return self.proc.poll() is None

    def stop(self) -> Optional[str]:
        with self._lock:
            proc, raw_path = self.proc, self.raw_path
            self.proc = None
        if not proc:
            return None
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        if raw_path and _wrap_raw(raw_path, self.wav_path or ""):
            return self.wav_path
        return None


def _vosk_model_dir() -> str:
    base = os.path.join(os.path.expanduser("~"), ".cache", "jarvis", "vosk")
    model_dir = os.path.join(base, VOSK_DIR_NAME)
    if os.path.isdir(model_dir):
        return model_dir
    zip_path = os.path.join(base, VOSK_DIR_NAME + ".zip")
    os.makedirs(base, exist_ok=True)
    if not os.path.exists(zip_path):
        import urllib.request
        print(f"[voice] Downloading Vosk model (~40 MB) to {base} ...", flush=True)
        urllib.request.urlretrieve(VOSK_URL, zip_path)
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(base)
    return model_dir


def _recognize_vosk(wav_path: str, model_dir: str) -> str:
    import wave
    rec = KaldiRecognizer(Model(model_dir), 16000)
    with wave.open(wav_path, "rb") as wf:
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
    return json.loads(rec.FinalResult()).get("text", "").strip()


def _recognize_whisper(wav_path: str) -> str:
    import openai
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    with open(wav_path, "rb") as fh:
        tr = client.audio.transcriptions.create(model="whisper-1", file=fh)
    return (tr.text or "").strip()


def recognize(wav_path: str, backend: str) -> str:
    """Transcribe a WAV file. backend: 'vosk' (offline) or 'whisper' (OpenAI API)."""
    if backend == "whisper":
        if os.environ.get("OPENAI_API_KEY"):
            return _recognize_whisper(wav_path)
        raise RuntimeError("voice.stt is 'whisper' but OPENAI_API_KEY is not set. Fall back to 'vosk' in config.")
    if Model is None:
        raise RuntimeError("vosk is not installed. Run: pip install vosk, or set voice.stt to 'whisper'.")
    return _recognize_vosk(wav_path, _vosk_model_dir())


def synth_speech(text: str, voice: str, out: str) -> None:
    """edge-tts synthesis with a few retries (mirrors the voiceover agent)."""
    import edge_tts
    last_exc: Optional[Exception] = None
    for attempt in range(4):
        try:
            async def _go() -> None:
                await edge_tts.Communicate(text, voice).save(out)
            asyncio.run(_go())
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"edge-tts failed: {last_exc}")


def play_audio(path: str) -> bool:
    player = find_player()
    if not player:
        return False
    try:
        if player == "ffplay":
            subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


class VoiceController:
    """Wires mic capture + STT + command parsing + voice replies into the orchestrator."""

    def __init__(self, orch, autopilot, emit: Callable[[str, dict], None]):
        self.orch = orch
        self.autopilot = autopilot
        self.emit = emit
        self.recorder = find_recorder()
        self.capture: Optional[CaptureSession] = None
        self.wake_on = False
        self._wake_thread: Optional[threading.Thread] = None
        self._awake_until = 0.0
        self._lock = threading.Lock()
        self.parser = CommandParser()

    # --- helpers ------------------------------------------------------------
    def _cfg(self, key: str, default):
        return self.orch.cfg.get("voice", key, default=default)

    def _event(self, type_: str, **data) -> None:
        self.emit("voice_event", {"type": type_, **data})

    def say(self, text: str) -> None:
        if not self._cfg("auto_voice_response", True):
            self._event("reply", text=text)
            return
        self._event("saying", text=text)
        try:
            out = os.path.join(_tmp_dir(), f"say_{int(time.time() * 1000)}.mp3")
            synth_speech(text, self._cfg("response_voice", "en-US-GuyNeural"), out)
            if not play_audio(out):
                self._event("no_player", text=text)
        except Exception as exc:  # noqa: BLE001
            self._event("reply", text=text, error=str(exc))

    # --- push to talk -------------------------------------------------------
    def push_to_talk_start(self) -> dict:
        if not self.recorder:
            self._event("error", message="No microphone recorder found (arecord/sox/ffmpeg).")
            return {"ok": False, "error": "no recorder"}
        with self._lock:
            if self.capture is None:
                self.capture = CaptureSession(self.recorder)
        ok = self.capture.start()
        self._event("listening", on=ok)
        return {"ok": ok, "listening": ok}

    def push_to_talk_stop(self) -> dict:
        with self._lock:
            cap, self.capture = self.capture, None
        if not cap:
            return {"ok": False, "listening": False}
        wav = cap.stop()
        self._event("listening", on=False)
        if not wav:
            self._event("error", message="Mic capture produced no audio.")
            return {"ok": False, "listening": False}
        threading.Thread(target=self._handle_wav, args=(wav,), daemon=True).start()
        return {"ok": True, "listening": False}

    # --- wake word loop -----------------------------------------------------
    def toggle_wake(self, on: bool) -> dict:
        if on == self.wake_on:
            return {"wake": self.wake_on}
        self.wake_on = on
        if on:
            self._wake_thread = threading.Thread(target=self._wake_loop, daemon=True)
            self._wake_thread.start()
            self._event("wake", on=True)
            self.say("Jarvis online. Awaiting command.")
        else:
            self._awake_until = 0.0
            self._event("wake", on=False)
        return {"wake": self.wake_on}

    def _wake_loop(self) -> None:
        if not self.recorder:
            return
        while self.wake_on:
            cap = CaptureSession(self.recorder)
            if not cap.start():
                time.sleep(2)
                continue
            time.sleep(max(1.5, self._cfg("push_to_talk_seconds", 8) / 3))
            wav = cap.stop()
            if not wav:
                continue
            try:
                text = recognize(wav, self._cfg("stt", "vosk"))
            except Exception as exc:  # noqa: BLE001
                self._event("error", message=f"STT unavailable: {exc}")
                time.sleep(5)
                continue
            self._event("heard", text=text)
            if self._awake_until > time.time():
                self._awake_until = 0.0
                self._dispatch(text)
            elif self._cfg("wake_word", "jarvis") and self._cfg("wake_word", "jarvis").lower() in text.lower():
                self._awake_until = time.time() + 6
                self._event("wake", on=True)
                self.say("Yes?")
            time.sleep(0.4)

    # --- command handling ---------------------------------------------------
    def _handle_wav(self, wav: str) -> None:
        try:
            text = recognize(wav, self._cfg("stt", "vosk"))
        except Exception as exc:  # noqa: BLE001
            self._event("error", message=f"Could not transcribe audio: {exc}")
            return
        self._event("heard", text=text)
        self._dispatch(text)

    def _dispatch(self, text: str) -> None:
        parsed = self.parser.parse(text)
        if not parsed:
            self.say("I didn't catch that. Try: make a video about AI, or upload to YouTube.")
            return
        action, params = parsed
        self._event("action", action=action, params=params)
        if action == "pipeline":
            self._run_pipeline(params.get("topic", ""))
        elif action == "upload":
            self._run_upload()
        elif action == "cancel":
            self.orch.request_cancel()
            self.say("Cancelling production.")
        elif action == "status":
            self._say_status()
        elif action == "autopilot_on":
            self.autopilot.start()
            self.say("Autopilot engaged. I'll keep producing videos automatically.")
        elif action == "autopilot_off":
            self.autopilot.stop()
            self.say("Autopilot disengaged.")
        elif action == "greeting":
            self.say("At your service. Say 'make a video' to begin production.")

    def _run_pipeline(self, topic: str) -> None:
        if self.orch.running:
            self.say("A pipeline is already running. I'll finish it first.")
            return
        vfmt = self._cfg("format", None) or self.orch.cfg.get("video", "format", default="vertical")
        params = {"topic": topic, "format": vfmt, "upload": bool(self.orch.cfg.get("channel", "auto_upload", default=False))}
        topic_txt = topic or "today's top trend"
        self.say(f"Starting production on {topic_txt}. Stand by.")
        threading.Thread(target=self._safe_pipeline, args=(params,), daemon=True).start()

    def _safe_pipeline(self, params: dict) -> None:
        try:
            res = self.orch.run_pipeline(params)
            if res.get("status") == "cancelled":
                self.say("Production cancelled.")
            else:
                self.say("Production complete. Your video is ready.")
        except Exception as exc:  # noqa: BLE001
            self.say(f"Production failed: {exc}")

    def _run_upload(self) -> None:
        if self.orch.running:
            self.say("The pipeline is busy. Try again when it finishes.")
            return
        self.say("Uploading the latest video to YouTube.")
        threading.Thread(target=self._safe_upload, daemon=True).start()

    def _safe_upload(self) -> None:
        try:
            res = self.orch.run_agent("upload", {"upload": True})
            vid = (res.get("result") or {}).get("video_id")
            self.say(f"Uploaded to YouTube. Video id {vid}.")
        except Exception as exc:  # noqa: BLE001
            self.say(f"Upload failed: {exc}")

    def _say_status(self) -> None:
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
        self.say(" ".join(parts))

    def status(self) -> dict:
        return {
            "available": self.recorder is not None,
            "recorder": self.recorder,
            "player": find_player(),
            "stt": self._cfg("stt", "vosk"),
            "wake_word": self._cfg("wake_word", "jarvis"),
            "wake_on": self.wake_on,
            "listening": bool(self.capture),
            "vosk_installed": Model is not None,
        }
