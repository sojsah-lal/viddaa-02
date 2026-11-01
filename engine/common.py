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

ROOT = Path(__file__).resolve().parent.parent
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


def mix(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


# ---------- look & feel ----------

@lru_cache(maxsize=4)
def background(accent: tuple, seed: int = 0) -> pygame.Surface:
    """Deep gradient, a faint accent glow behind the action, vignette and a few stars."""
    import numpy as np
    y = np.linspace(0, 1, H)[None, :, None]
    x = np.linspace(0, 1, W)[:, None, None]
    top, bottom = np.array([18, 14, 34]), np.array([6, 6, 14])
    img = top * (1 - y) + bottom * y
    d = np.sqrt(((x - 0.5) * 1.1) ** 2 + ((y - 0.55) * 0.62) ** 2)
    img = img + np.array(accent) * 0.10 * np.clip(1 - d / 0.45, 0, 1) ** 2
    img = img * np.clip(1.15 - d * 0.9, 0.55, 1.0)
    surf = pygame.surfarray.make_surface(np.clip(img, 0, 255).astype(np.uint8))
    rng = __import__("random").Random(seed)
    for _ in range(140):
        v = rng.randint(40, 110)
        surf.set_at((rng.randrange(W), rng.randrange(H)), (v, v, v + 20))
    return surf


class Glow:
    """Neon bloom: blur the frame at two scales, subtract the (static) background, add back."""
    LEVELS = ((6, 0.85), (20, 0.75))

    def __init__(self, bg: pygame.Surface, strength: float = 1.0):
        self.k = strength
        self.base = [pygame.transform.smoothscale(bg, (W // f, H // f)) for f, _ in self.LEVELS]

    def apply(self, frame: pygame.Surface):
        for (f, k), base in zip(self.LEVELS, self.base):
            s = pygame.transform.smoothscale(frame, (W // f, H // f))
            s.blit(base, (0, 0), special_flags=pygame.BLEND_SUB)
            g = int(255 * min(1.0, k * self.k))
            s.fill((g, g, g), special_flags=pygame.BLEND_MULT)
            frame.blit(pygame.transform.smoothscale(s, (W, H)), (0, 0), special_flags=pygame.BLEND_ADD)


def draw_trail(dst, pts, color, r0, alpha0=170, step=6.0):
    """Comet trail through pts (oldest -> newest), tapering in size and alpha."""
    samples = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        if d > 400:  # teleport (camera cut); restart trail
            samples = []
            continue
        n = max(1, int(d / step))
        samples += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n)]
    n = len(samples)
    for i, (x, y) in enumerate(samples):
        f = (i + 1) / n
        aa_circle(dst, (*color, int(alpha0 * f * f)), x, y, max(1.0, r0 * (0.25 + 0.75 * f)))


@lru_cache(maxsize=64)
def face_disc(path: Path, r: int) -> pygame.Surface:
    """Portrait cropped to a circle of radius r (square crop biased to the top, where faces usually are)."""
    img = pygame.image.load(str(path))
    w, h = img.get_size()
    side = min(w, h)
    x0, y0 = (w - side) // 2, int((h - side) * 0.15)
    img = pygame.transform.smoothscale(img.subsurface((x0, y0, side, side)), (2 * r, 2 * r))
    out = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
    out.blit(img, (0, 0))
    mask = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
    pygame.gfxdraw.filled_circle(mask, r, r, r - 1, (255, 255, 255, 255))
    pygame.gfxdraw.aacircle(mask, r, r, r - 1, (255, 255, 255, 255))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return out


def make_burst(seed, x, y, colors, n=24, speed=(150, 500), life=0.45, size=(3, 6)):
    """Seeded spark burst: list of (x, y, vx, vy, size, life, color)."""
    import random
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        a = rng.uniform(0, 2 * math.pi)
        sp = rng.uniform(*speed)
        out.append((x, y, sp * math.cos(a), sp * math.sin(a), rng.uniform(*size), life * rng.uniform(0.7, 1.2),
                    rng.choice(colors)))
    return out


def draw_burst(dst, parts, age, gravity=900, dy=0.0):
    for (x, y, vx, vy, s, life, col) in parts:
        if not 0 <= age < life:
            continue
        k = 1 - age / life
        aa_circle(dst, (*lighten(col, 0.3 * k), int(255 * k)), x + vx * age, y + vy * age + 0.5 * gravity * age * age
                  + dy, s * (0.4 + 0.6 * k))


def make_confetti(seed, colors, n=140):
    import random
    rng = random.Random(seed)
    return [(rng.uniform(0, W), rng.uniform(-1500, -40), rng.uniform(-90, 90), rng.uniform(450, 850),
             rng.uniform(8, 16), rng.uniform(0, 6.28), rng.uniform(-9, 9), rng.choice(colors)) for _ in range(n)]


def draw_confetti(dst, pieces, age):
    for (x, y, vx, vy, s, a0, spin, col) in pieces:
        px, py = x + vx * age + 30 * math.sin(age * 3 + a0), y + vy * age
        if py < -30 or py > H + 30:
            continue
        a = a0 + spin * age
        w, h = s, s * 0.5 * abs(math.cos(a * 0.7)) + 2
        c, sn = math.cos(a), math.sin(a)
        pts = [(px + dx * c - dy * sn, py + dx * sn + dy * c) for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h))]
        pygame.gfxdraw.filled_polygon(dst, pts, col)
        pygame.gfxdraw.aapolygon(dst, pts, col)


def shaken(dst, scene, amp, t, seed=0):
    """Blit scene onto dst with a decaying random shake of amplitude amp (px)."""
    if amp < 0.5:
        dst.blit(scene, (0, 0))
        return
    dx = amp * math.sin(t * 91.0 + seed)
    dy = amp * math.cos(t * 77.0 + seed * 1.7)
    dst.fill(BG)
    dst.blit(scene, (int(dx), int(dy)))


def flash(dst, color, alpha):
    if alpha <= 1:
        return
    s = pygame.Surface((W, H), pygame.SRCALPHA)
    s.fill((*color, int(min(255, alpha))))
    dst.blit(s, (0, 0))


def pop_text(dst, text, base, color, cx, cy, pop=0.0, alpha=255, stroke=5):
    """Text that briefly scales up (pop 0..1); sizes are quantized so the glyph cache stays small."""
    size = int(base * (1 + 0.45 * pop)) // 4 * 4
    surf = text_surface(text, size, color, stroke)
    if alpha < 255:
        surf = surf.copy()
        surf.set_alpha(alpha)
    blit_center(dst, surf, cx, cy)


# ---------- end card ----------

def draw_end_card(dst, background, title, subtitle, accent, progress, confetti=None, hero=None):
    """background: frozen last scene; progress 0..1 drives fade/scale-in; confetti from make_confetti();
    hero: optional round portrait shown above the title."""
    dst.blit(background, (0, 0))
    k = min(1.0, progress / 0.25)
    shade = pygame.Surface((W, H), pygame.SRCALPHA)
    # tinted, not black, so blackdetect never flags the end card
    shade.fill((*(int(v * 0.35) + 18 for v in accent), int(215 * k)))
    dst.blit(shade, (0, 0))
    if confetti:
        draw_confetti(dst, confetti, progress * END_CARD_SECONDS + 0.3)
    # back-out ease: overshoots slightly, then settles
    ease = 1 + 2.7 * (k - 1) ** 3 + 1.7 * (k - 1) ** 2
    title_size = max(40, int(150 * (0.55 + 0.45 * ease)) // 4 * 4)
    if hero is not None:
        s = max(8, int(hero.get_width() * min(1.0, 0.4 + 0.6 * ease)))
        aa_circle(dst, (*accent, 120), W / 2, 600, s / 2 + 14)
        aa_circle(dst, accent, W / 2, 600, s / 2 + 6)
        blit_center(dst, pygame.transform.smoothscale(hero, (s, s)), W / 2, 600)
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
