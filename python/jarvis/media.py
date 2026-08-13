"""PIL-based media generation: fonts, backgrounds, subtitle frames, thumbnails."""
from __future__ import annotations

import os
import random
import textwrap

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover - lets the rest of Jarvis load without Pillow
    Image = ImageDraw = ImageFilter = ImageFont = None

_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"),
]

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _require_pil() -> None:
    if Image is None:
        raise RuntimeError(
            "Pillow is not installed. Run: pip install -r python/requirements.txt"
        )


def _font(bold: bool = True, size: int = 40) -> ImageFont.FreeTypeFont:
    _require_pil()
    key = ("b" if bold else "r", size)
    if key in _font_cache:
        return _font_cache[key]
    for bold_path, reg_path in _FONT_CANDIDATES:
        path = bold_path if bold else reg_path
        if os.path.exists(path):
            f = ImageFont.truetype(path, size)
            _font_cache[key] = f
            return f
    f = ImageFont.load_default(size=size)
    _font_cache[key] = f
    return f


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        px[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return img.resize((w, h))


def _grid_glow(img: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for x in range(0, w, 90):
        d.line([(x, 0), (x, h)], fill=(255, 255, 255), width=1)
    for y in range(0, h, 90):
        d.line([(0, y), (w, y)], fill=(255, 255, 255), width=1)
    overlay = overlay.filter(ImageFilter.GaussianBlur(1))
    img = Image.blend(img, overlay, 0.05)

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dg = ImageDraw.Draw(glow)
    cx, cy, r = random.randint(w // 3, 2 * w // 3), random.randint(h // 4, h // 2), min(w, h) // 3
    dg.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent + (60,))
    glow = glow.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    return img.convert("RGB")


def make_background(size: tuple[int, int], keyword: str, index: int) -> Image.Image:
    _require_pil()
    w, h = size
    palettes = [
        ((10, 20, 40), (90, 30, 60)),
        ((5, 10, 35), (20, 60, 110)),
        ((20, 8, 30), (110, 30, 40)),
        ((8, 25, 30), (20, 90, 90)),
    ]
    top, bottom = palettes[index % len(palettes)]
    img = _gradient(size, top, bottom)
    img = _grid_glow(img, (120, 180, 255) if index % 2 == 0 else (255, 140, 200))

    d = ImageDraw.Draw(img)
    big = _font(bold=True, size=w // 7)
    text = keyword.upper()[:18]
    tw, th = _text_size(d, text, big)
    d.text(((w - tw) / 2, h * 0.32 - th / 2), text, fill=(255, 255, 255), font=big)

    accent = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(accent).rectangle([0, 0, w, 14], fill=(255, 0, 80, 220))
    img = Image.alpha_composite(img.convert("RGBA"), accent)
    return img.convert("RGB")


def _rounded_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def make_subtitle_frame(size: tuple[int, int], text: str) -> Image.Image:
    """Full-frame transparent image with the subtitle rendered near the bottom."""
    _require_pil()
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font(bold=True, size=int(w * 0.055))
    max_w = int(w * 0.86)
    lines = []
    for raw in text.split("\n"):
        wrapped = textwrap.wrap(raw, width=max(1, int(max_w / (font.size * 0.62))))
        lines.extend(wrapped or [raw])
    lines = lines[:3]
    if len(lines) > 2:
        lines = [lines[0], lines[1] + " …"]
    line_h = font.size + int(w * 0.02)
    block_h = line_h * len(lines) + int(w * 0.035)
    box_h = int(w * 0.24)
    y0 = int(h - box_h)
    _rounded_box(d, (int(w * 0.02), y0, int(w * 0.98), h - int(w * 0.02)), radius=int(w * 0.03), fill=(0, 0, 0, 130))
    cy = y0 + int((box_h - block_h) / 2)
    for line in lines:
        tw, th = _text_size(d, line, font)
        tx = (w - tw) / 2
        d.text((tx + 2, cy + 2), line, fill=(0, 0, 0), font=font)
        d.text((tx, cy), line, fill=(255, 255, 255), font=font)
        cy += line_h
    return img


def make_thumbnail(title: str, subtitle: str, channel_name: str) -> Image.Image:
    _require_pil()
    W, H = 1280, 720
    img = _gradient((W, H), (12, 16, 42), (90, 20, 70))
    img = _grid_glow(img, (255, 220, 0))

    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 18], fill=(255, 0, 80))

    title_font = _font(bold=True, size=88)
    lines = textwrap.wrap(title, width=16)[:3]
    cy = 130
    for line in lines:
        tw, th = _text_size(d, line, title_font)
        d.text(((W - tw) / 2 + 4, cy + 4), line, fill=(0, 0, 0), font=title_font)
        d.text(((W - tw) / 2, cy), line, fill=(255, 255, 255), font=title_font)
        cy += th + 12

    if subtitle:
        sub_font = _font(bold=False, size=46)
        sw, _ = _text_size(d, subtitle, sub_font)
        d.rectangle([(W - sw) / 2 - 24, 560, (W + sw) / 2 + 24, 640], fill=(255, 0, 80))
        d.text(((W - sw) / 2, 575), subtitle, fill=(255, 255, 255), font=sub_font)

    brand_font = _font(bold=True, size=30)
    bw, bh = _text_size(d, channel_name, brand_font)
    d.rounded_rectangle([W - bw - 60, H - bh - 55, W - 30, H - 25], radius=14, fill=(30, 30, 30))
    d.text((W - bw - 45, H - bh - 42), channel_name, fill=(255, 255, 255), font=brand_font)
    return img
