"""Agent 3/6 — Voiceover: TTS per sentence (edge-tts by default, ElevenLabs optional)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import time

from ..agent import Agent, ensure_tools, probe_duration, run_cmd


class VoiceAgent(Agent):
    """Synthesizes narration audio per sentence so timing maps to subtitles."""

    name = "voice"

    def run(self, orch, ctx: dict) -> dict:
        script = ctx.get("script") or self.artifact(ctx, "script")
        if not script.get("sentences"):
            raise RuntimeError("No sentences available — run the script stage first.")

        audio_dir = os.path.join(ctx["workdir"], "audio")
        os.makedirs(audio_dir, exist_ok=True)
        ensure_tools(["ffmpeg", "ffprobe"])
        provider = orch.cfg.get("tts", "provider", default="edge")

        timings = []
        total = len(script["sentences"])
        for i, sentence in enumerate(script["sentences"]):
            self.check_cancel()
            seg_path = os.path.join(audio_dir, f"seg_{i:03d}.mp3")
            self.progress("synthesizing", i / total * 90)
            self.log(f"Voiceover {i + 1}/{total}: {sentence[:60]}")
            if provider == "elevenlabs":
                self._elevenlabs(orch, sentence, seg_path)
            else:
                self._edge(orch, sentence, seg_path)
            if i < total - 1:
                time.sleep(0.7)  # pace requests to avoid TTS throttling
            duration = probe_duration(seg_path)
            timings.append({"index": i, "text": sentence, "audio": seg_path, "duration": round(duration, 3)})
        self.check_cancel()

        narration = os.path.join(audio_dir, "narration.mp3")
        self._concat(audio_dir, narration)
        total_duration = probe_duration(narration)
        self.log(f"Narration ready: {total_duration:.1f}s")
        self.progress("done", 100)
        return {"timings": timings, "narration": narration, "duration": round(total_duration, 3)}

    # --- providers -----------------------------------------------------------
    def _edge(self, orch, text: str, out: str) -> None:
        import edge_tts
        voice = orch.cfg.get("tts", "voice", default="en-US-ChristopherNeural")
        rate = orch.cfg.get("tts", "rate", default="+10%")

        async def synth() -> None:
            comm = edge_tts.Communicate(text, voice, rate=rate)
            await comm.save(out)

        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                asyncio.run(synth())
                if os.path.exists(out) and os.path.getsize(out) > 1000:
                    return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            self.log(f"edge-tts attempt {attempt + 1}/4 failed — retrying...", "warn")
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"edge-tts failed after 3 attempts: {last_exc}")

    def _elevenlabs(self, orch, text: str, out: str) -> None:
        import os as _os
        import requests
        key = _os.environ.get(orch.cfg.get("tts", "elevenlabs_api_key_env", default="ELEVENLABS_API_KEY"))
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not set. Run setup or switch tts.provider back to 'edge'.")
        voice_id = orch.cfg.get("tts", "elevenlabs_voice_id", default="")
        if not voice_id:
            voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        resp = requests.post(
            url,
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"ElevenLabs error {resp.status_code}: {resp.text[:200]}")
        with open(out, "wb") as fh:
            fh.write(resp.content)

    def _concat(self, audio_dir: str, out: str) -> None:
        segs = sorted(p for p in os.listdir(audio_dir) if p.startswith("seg_") and p.endswith(".mp3"))
        if not segs:
            raise RuntimeError("No audio segments generated.")
        list_file = os.path.join(audio_dir, "concat.txt")
        with open(list_file, "w", encoding="utf-8") as fh:
            for seg in segs:
                path = os.path.join(audio_dir, seg).replace("'", "'\\''")
                fh.write(f"file '{path}'\n")
        run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out], self.log)
