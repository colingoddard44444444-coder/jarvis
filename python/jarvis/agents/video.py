"""Agent 4/6 — Video Editor: builds the montage + burned subtitles with ffmpeg only."""
from __future__ import annotations

import math
import os

from .. import media
from ..agent import Agent, ensure_tools, probe_duration, run_cmd

FPS = 30


class VideoAgent(Agent):
    """Assembles background montage (Ken Burns), subtitles and narration into a final MP4."""

    name = "video"

    def run(self, orch, ctx: dict) -> dict:
        script = ctx.get("script") or self.artifact(ctx, "script")
        voice = ctx.get("voice") or self.artifact(ctx, "voice")
        timings = voice.get("timings")
        if not timings:
            raise RuntimeError("No voiceover timings — run the voice stage first.")
        ensure_tools(["ffmpeg", "ffprobe"])

        params = ctx.get("params", {})
        vfmt = params.get("format") or orch.cfg.get("video", "format", default="vertical")
        if vfmt == "horizontal":
            w, h = 1920, 1080
        else:
            w, h = 1080, 1920
        total = voice.get("duration", sum(t["duration"] for t in timings))
        self.log(f"Rendering {vfmt} video: {w}x{h}, ~{total:.0f}s, {len(timings)} segments")

        seg_dir = os.path.join(ctx["workdir"], "segments")
        sub_dir = os.path.join(ctx["workdir"], "subtitles")
        os.makedirs(seg_dir, exist_ok=True)
        os.makedirs(sub_dir, exist_ok=True)

        seg_paths, sub_paths = [], []
        cumulative = 0.0
        keyword = (script.get("title") or orch.cfg.get("channel", "niche", default="AI & Tech"))[:30]
        for i, t in enumerate(timings):
            self.check_cancel()
            self.progress("rendering", i / len(timings) * 85)
            dur = max(0.6, t["duration"])
            bg = os.path.join(seg_dir, f"bg_{i:03d}.png")
            seg = os.path.join(seg_dir, f"seg_{i:03d}.mp4")
            media.make_background((w, h), keyword, i).save(bg)
            self._ken_burns(bg, seg, dur, w, h)
            if orch.cfg.get("video", "subtitles", default=True):
                sub = os.path.join(sub_dir, f"sub_{i:03d}.png")
                media.make_subtitle_frame((w, h), t["text"]).save(sub)
                sub_paths.append((sub, cumulative, cumulative + dur))
            seg_paths.append(seg)
            cumulative += dur

        final = os.path.join(ctx["workdir"], "final.mp4")
        self.progress("muxing", 90)
        self._assemble(seg_paths, sub_paths, voice["narration"], final, total, w, h)
        duration = probe_duration(final)
        self.log(f"Video ready: {final} ({duration:.1f}s)")
        self.progress("done", 100)
        return {"video": final, "duration": round(duration, 3), "format": vfmt}

    def _ken_burns(self, bg_png: str, out_mp4: str, dur: float, w: int, h: int) -> None:
        frames = max(15, int(math.ceil(dur * FPS)))
        step = 0.18 / frames
        vf = (
            f"scale={w * 2}:{h * 2},"
            f"zoompan=z='min(zoom+{step:.6f},1.3)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}"
        )
        run_cmd(
            [
                "ffmpeg", "-y", "-i", bg_png,
                "-vf", vf,
                "-frames:v", str(frames),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                out_mp4,
            ],
            self.log,
            timeout=900,
        )

    def _assemble(self, seg_paths, sub_paths, narration, final, total, w, h) -> None:
        n = len(seg_paths)
        inputs: list[str] = []
        for p in seg_paths:
            inputs += ["-i", p]
        for p, _, _ in sub_paths:
            inputs += ["-i", p]
        inputs += ["-i", narration]

        filters: list[str] = []
        for i in range(n):
            filters.append(f"[{i}:v]fps={FPS},format=yuv420p[s{i}]")
        filters.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[bg]")
        prev = "bg"
        for j, (_, s, e) in enumerate(sub_paths):
            idx = n + j
            filters.append(
                f"[{prev}][{idx}:v]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'[ov{j}]"
            )
            prev = f"ov{j}"
        a_idx = n + len(sub_paths)
        filters.append(f"[{a_idx}:a]aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=44100[a]")

        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(filters),
            "-map", f"[{prev}]", "-map", "[a]",
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            final,
        ]
        run_cmd(cmd, self.log, timeout=3600)
