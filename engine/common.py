"""Shared rendering helpers: canvas, colors, text, end card, FFmpeg frame writer."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import glob
import math
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pygame
import pygame.gfxdraw

W, H = 1080, 1920
FPS = 30
HOOK_TOP, HOOK_BOTTOM = 180, 420   # hook text must stay inside this band
BOTTOM_UI = 350                    # TikTok overlays the bottom 350 px
BG = (11, 11, 18)
WHITE = (245, 245, 250)
END_CARD_SECONDS = 2.2
DEFAULT_PALETTE = ["#FF4D6D", "#4DD2FF", "#FFD24D", "#7CFF4D", "#C77DFF", "#FF9F1C"]


def init() -> pygame.Surface:
    pygame.init()
    return pygame.Surface((W, H))


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    """Find ffmpeg/ffprobe: env override, PATH, then the WinGet install folder."""
    env = os.environ.get(f"{name.upper()}_BIN")
    if env:
        return env
    found = shutil.which(name)
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        hits = glob.glob(str(Path(local) / "Microsoft/WinGet/Packages/Gyan.FFmpeg*/**/bin" / f"{name}.exe"),
                         recursive=True)
        if hits:
            return hits[0]
    raise FileNotFoundError(f"{name} not found; install FFmpeg and put it on PATH")


def hex_to_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def palette_rgb(config: dict) -> list:
    return [hex_to_rgb(c) for c in (config.get("palette") or DEFAULT_PALETTE)]


def lighten(c, amt=0.4):
    return tuple(int(v + (255 - v) * amt) for v in c)


def clean_text(s: str) -> str:
    """Drop emoji / symbols the bundled font cannot draw."""
    out = []
    for ch in s:
        o = ord(ch)
        if o > 0xFFFF or 0x2600 <= o <= 0x27BF or 0xFE00 <= o <= 0xFE0F or o == 0x200D:
            continue
        out.append(ch)
    return " ".join("".join(out).split())


# ---------- text ----------

@lru_cache(maxsize=64)
def font(size: int) -> pygame.font.Font:
    return pygame.font.Font(None, size)


@lru_cache(maxsize=512)
def text_surface(text: str, size: int, color: tuple, stroke: int = 4) -> pygame.Surface:
    f = font(size)
    fg = f.render(text, True, color)
    if stroke <= 0:
        return fg
    outline = f.render(text, True, (0, 0, 0))
    surf = pygame.Surface((fg.get_width() + stroke * 2, fg.get_height() + stroke * 2), pygame.SRCALPHA)
    for dx in range(-stroke, stroke + 1, max(1, stroke // 2)):
        for dy in range(-stroke, stroke + 1, max(1, stroke // 2)):
            if dx * dx + dy * dy <= stroke * stroke:
                surf.blit(outline, (dx + stroke, dy + stroke))
    surf.blit(fg, (stroke, stroke))
    return surf


def wrap(text: str, size: int, max_w: int) -> list:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font(size).size(trial)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def blit_center(dst: pygame.Surface, surf: pygame.Surface, cx: float, cy: float):
    dst.blit(surf, (int(cx - surf.get_width() / 2), int(cy - surf.get_height() / 2)))


def draw_lines(dst, lines, size, color, cx, cy, stroke=4, spacing=1.05):
    line_h = font(size).get_linesize() * spacing
    top = cy - line_h * len(lines) / 2 + line_h / 2
    for i, ln in enumerate(lines):
        blit_center(dst, text_surface(ln, size, color, stroke), cx, top + i * line_h)


@lru_cache(maxsize=8)
def hook_layout(text: str) -> tuple:
    """Largest font size whose wrapped hook fits the safe band."""
    text = clean_text(text).upper()
    band = HOOK_BOTTOM - HOOK_TOP
    for size in range(120, 56, -4):
        lines = wrap(text, size, 960)
        if len(lines) * font(size).get_linesize() * 1.05 <= band:
            return lines, size
    return wrap(text, 56, 960), 56


def draw_hook(dst, text, color=WHITE):
    lines, size = hook_layout(text)
    draw_lines(dst, lines, size, color, W / 2, (HOOK_TOP + HOOK_BOTTOM) / 2, stroke=6)


# ---------- shapes ----------

def aa_circle(dst, color, x, y, r):
    x, y, r = int(round(x)), int(round(y)), max(1, int(round(r)))
    pygame.gfxdraw.filled_circle(dst, x, y, r, color)
    pygame.gfxdraw.aacircle(dst, x, y, r, color)


def aa_arc(dst, color, cx, cy, r, thickness, a0, a1, step=0.03):
    """Thick anti-aliased arc from angle a0 to a1 (radians, a1 > a0)."""
    n = max(4, int((a1 - a0) / step))
    ro, ri = r + thickness / 2, r - thickness / 2
    outer = [(cx + ro * math.cos(a0 + (a1 - a0) * i / n), cy + ro * math.sin(a0 + (a1 - a0) * i / n))
             for i in range(n + 1)]
    inner = [(cx + ri * math.cos(a1 - (a1 - a0) * i / n), cy + ri * math.sin(a1 - (a1 - a0) * i / n))
             for i in range(n + 1)]
    pts = outer + inner
    pygame.gfxdraw.filled_polygon(dst, pts, color)
    pygame.gfxdraw.aapolygon(dst, pts, color)


# ---------- end card ----------

def draw_end_card(dst, background, title, subtitle, accent, progress):
    """background: frozen last scene; progress 0..1 drives fade/scale-in."""
    dst.blit(background, (0, 0))
    k = min(1.0, progress / 0.25)
    shade = pygame.Surface((W, H), pygame.SRCALPHA)
    # tinted, not black, so blackdetect never flags the end card
    shade.fill((*(int(v * 0.35) + 18 for v in accent), int(215 * k)))
    dst.blit(shade, (0, 0))
    ease = 1 - (1 - k) ** 3
    title_size = int(150 * (0.7 + 0.3 * ease))
    draw_lines(dst, wrap(clean_text(title).upper(), title_size, 980), title_size, accent, W / 2, 820, stroke=7)
    draw_lines(dst, wrap(clean_text(subtitle), 84, 960), 84, WHITE, W / 2, 1010, stroke=5)
    if progress > 0.3:
        draw_lines(dst, ["Follow for tomorrow's challenge!"], 64, lighten(accent, 0.3), W / 2, 1200, stroke=4)


# ---------- output ----------

class FrameWriter:
    """Pipes raw RGB frames into FFmpeg (video only)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.frames = 0
        self.proc = None

    def __enter__(self):
        cmd = [ffmpeg_bin(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
               str(self.path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        return self

    def write(self, surface: pygame.Surface):
        self.proc.stdin.write(pygame.image.tobytes(surface, "RGB"))
        self.frames += 1

    @property
    def seconds(self) -> float:
        return self.frames / FPS

    def __exit__(self, exc_type, exc, tb):
        self.proc.stdin.close()
        rc = self.proc.wait()
        if rc != 0 and exc_type is None:
            raise RuntimeError(f"ffmpeg exited with code {rc}")
        return False
