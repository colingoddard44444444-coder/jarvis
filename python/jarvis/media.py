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


JARVIS_GREEN = (0, 224, 160)
JARVIS_AMBER = (255, 190, 90)


def _glow_composite(base: Image.Image, draw_fn, radius: int) -> Image.Image:
    """Draw into a transparent layer, blur it, and composite it onto base (soft glow)."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


def _vignette(img: Image.Image) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([-w * 0.35, -h * 0.30, w * 1.35, h * 1.30], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(w, h) // 12))
    return Image.composite(img, Image.new("RGB", (w, h), (0, 0, 0)), mask)


def _jarvis_background(size: tuple[int, int], keyword: str, index: int) -> Image.Image:
    """Iron-Man-style HUD background: dark gradient, scanlines, corner brackets, reticle."""
    _require_pil()
    w, h = size
    img = _vignette(_gradient(size, (5, 14, 26), (1, 3, 8)))

    scan = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(scan)
    for y in range(0, h, 4):
        d.line([(0, y), (w, y)], fill=JARVIS_GREEN + (10,), width=1)
    for x in range(0, w, 100):
        d.line([(x, 0), (x, h)], fill=JARVIS_GREEN + (16,), width=1)
    for y in range(0, h, 100):
        d.line([(0, y), (w, y)], fill=JARVIS_GREEN + (12,), width=1)
    img = Image.alpha_composite(img.convert("RGBA"), scan).convert("RGB")

    m, L, t = int(w * 0.04), int(w * 0.10), max(4, w // 135)

    def bracket(ox: int, oy: int, sx: int, sy: int) -> Image.Image:
        img2 = _glow_composite(img, lambda bd: (
            bd.line([(ox, oy), (ox + sx * L, oy)], fill=JARVIS_GREEN + (255,), width=t),
            bd.line([(ox, oy), (ox, oy + sy * L)], fill=JARVIS_GREEN + (255,), width=t),
        ), 6)
        ImageDraw.Draw(img2).line([(ox, oy), (ox + sx * L, oy)], fill=JARVIS_GREEN, width=t)
        ImageDraw.Draw(img2).line([(ox, oy), (ox, oy + sy * L)], fill=JARVIS_GREEN, width=t)
        return img2

    img = bracket(m, m, 1, 1)
    img = bracket(w - m, m, -1, 1)
    img = bracket(m, h - m, 1, -1)
    img = bracket(w - m, h - m, -1, -1)

    cx, cy, r = int(w * 0.76), int(h * 0.26), int(w * 0.10)
    def reticle(bd, alpha):
        col = JARVIS_AMBER + (alpha,)
        bd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=3)
        for k in (-1, 0, 1):
            bd.line([(cx - r * 0.9, cy + k * r * 0.35), (cx - r * 1.25, cy + k * r * 0.35)], fill=col, width=3)
            bd.line([(cx + r * 0.9, cy + k * r * 0.35), (cx + r * 1.25, cy + k * r * 0.35)], fill=col, width=3)
    img = _glow_composite(img, lambda bd: reticle(bd, 255), 4)
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], outline=JARVIS_AMBER, width=3)
    rd = ImageDraw.Draw(img)
    rd.line([(cx, cy - r - 10), (cx, cy - r - 22)], fill=JARVIS_AMBER, width=3)
    rd.line([(cx, cy + r + 10), (cx, cy + r + 22)], fill=JARVIS_AMBER, width=3)
    rd.line([(cx - r - 10, cy), (cx - r - 22, cy)], fill=JARVIS_AMBER, width=3)
    rd.line([(cx + r + 10, cy), (cx + r + 22, cy)], fill=JARVIS_AMBER, width=3)

    big = _font(bold=True, size=w // 6)
    text = keyword.upper()[:18]
    tw, th = _text_size(ImageDraw.Draw(img), text, big)
    kx, ky = (w - tw) / 2, h * 0.30 - th / 2
    img = _glow_composite(img, lambda bd: bd.text((kx, ky), text, fill=JARVIS_GREEN + (255,), font=big), int(w * 0.014))
    d = ImageDraw.Draw(img)
    d.text((kx + 3, ky + 3), text, fill=(0, 0, 0), font=big)
    d.text((kx, ky), text, fill=(232, 255, 247), font=big)

    h1 = _font(bold=True, size=int(w * 0.024))
    h2 = _font(bold=True, size=int(w * 0.018))
    d.text((m, int(h * 0.05)), "JARVIS // ONLINE", fill=JARVIS_GREEN, font=h1)
    d.text((m, int(h * 0.085)), f"UNIT 07 · SEG {index + 1:02d}", fill=JARVIS_AMBER, font=h2)
    mode_w = _text_size(d, "AUTONOMOUS MODE", h2)[0]
    d.text((w - m - mode_w, int(h * 0.05)), "AUTONOMOUS MODE", fill=JARVIS_GREEN, font=h2)

    rnd = random.Random(index)
    hex_font = _font(bold=False, size=int(w * 0.018))
    for row in range(12):
        y = int(h * 0.20) + row * int(h * 0.022)
        s = " ".join(f"{rnd.randint(0, 255):02X}" for _ in range(4))
        d.text((m, y), s, fill=JARVIS_GREEN, font=hex_font)

    yb = h - int(h * 0.045)
    d.line([(m, yb), (w - m, yb)], fill=(0, 70, 55), width=t)
    pct = ((index + 1) % 12) * 8.33
    d.line([(m, yb), (m + (w - 2 * m) * pct / 100.0, yb)], fill=JARVIS_GREEN, width=t)
    d.text((m, yb - int(h * 0.03)), "SYSTEM READY // PRODUCTION", fill=JARVIS_GREEN, font=h2)
    return img


def make_background(size: tuple[int, int], keyword: str, index: int, style: str = "tech") -> Image.Image:
    _require_pil()
    if style == "jarvis":
        return _jarvis_background(size, keyword, index)
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


def _wrap_lines(text: str, font, max_w: int, max_lines: int = 3) -> list[str]:
    lines: list[str] = []
    for raw in text.split("\n"):
        wrapped = textwrap.wrap(raw, width=max(1, int(max_w / (font.size * 0.62))))
        lines.extend(wrapped or [raw])
    if len(lines) > max_lines - 1:
        lines = [lines[0], lines[1] + " …"]
    return lines[: max_lines - 1]


def _jarvis_subtitle(size: tuple[int, int], text: str) -> Image.Image:
    """Bottom HUD panel with a glowing green border and a '»' cue."""
    _require_pil()
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    font = _font(bold=True, size=int(w * 0.052))
    lines = _wrap_lines(text, font, int(w * 0.80))
    line_h = font.size + int(w * 0.02)
    block_h = line_h * len(lines) + int(w * 0.04)
    box_h = int(w * 0.22)
    y0 = int(h - box_h - int(w * 0.04))
    box = (int(w * 0.06), y0, int(w * 0.94), y0 + box_h)

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(box, radius=int(w * 0.03), outline=JARVIS_GREEN + (255,), width=5)
    glow = glow.filter(ImageFilter.GaussianBlur(8))
    img = Image.alpha_composite(img, glow)
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(box, radius=int(w * 0.03), fill=(1, 10, 16, 195), outline=JARVIS_GREEN, width=2)
    img = Image.alpha_composite(img, panel)

    d = ImageDraw.Draw(img)
    cy = y0 + int((box_h - block_h) / 2)
    for i, line in enumerate(lines):
        tw, th = _text_size(d, line, font)
        if i == 0:
            prefix = "» "
            pw = _text_size(d, prefix, font)[0]
            tx = (w - tw - pw) / 2
            gl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(gl).text((tx + pw, cy), line, fill=(255, 255, 255, 220), font=font)
            gl = gl.filter(ImageFilter.GaussianBlur(3))
            img = Image.alpha_composite(img, gl)
            d = ImageDraw.Draw(img)
            d.text((tx + 2 + pw, cy + 2), line, fill=(0, 0, 0), font=font)
            d.text((tx + pw, cy), line, fill=(240, 255, 250), font=font)
            d.text((tx, cy + 2), prefix, fill=JARVIS_GREEN, font=font)
            d.text((tx, cy), prefix, fill=JARVIS_AMBER, font=font)
        else:
            tx = (w - tw) / 2
            d.text((tx + 2, cy + 2), line, fill=(0, 0, 0), font=font)
            d.text((tx, cy), line, fill=(240, 255, 250), font=font)
        cy += line_h
    return img


def make_subtitle_frame(size: tuple[int, int], text: str, style: str = "tech") -> Image.Image:
    """Full-frame transparent image with the subtitle rendered near the bottom."""
    _require_pil()
    if style == "jarvis":
        return _jarvis_subtitle(size, text)
    w, h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _font(bold=True, size=int(w * 0.055))
    lines = _wrap_lines(text, font, int(w * 0.86))
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
