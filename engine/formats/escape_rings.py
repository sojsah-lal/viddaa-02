"""escape_rings: "Can the ball escape all N rings?" — rotating concentric rings with gaps.

Balls bounce inside the innermost ring; when any ball slips through its gap that ring shatters.
With balls > 1 all balls share the rings, so there is no single winning ball. Ends with
"ESCAPED in X.Xs" or, if time runs out, "TIME'S UP! N rings left".
"""
import math
import random
from dataclasses import dataclass, field

import pygame

from engine import common as C

NAME = "escape_rings"
PARAM_RANGES = {
    "rings": (5, 15, int),
    "gap_deg": (30, 70, float),
    "gravity": (0.2, 0.9, float),
    "grow_per_bounce": (0.0, 0.05, float),
    "speed_up_per_bounce": (0.0, 0.03, float),
    "spin": (40, 200, float),
    "balls": (1, 3, int),
    "max_seconds": (20, 40, float),
}
DEFAULTS = {"rings": 10, "gap_deg": 50, "gravity": 0.45, "grow_per_bounce": 0.01,
            "speed_up_per_bounce": 0.0, "spin": 90, "balls": 1, "max_seconds": 38}

CX, CY = C.W / 2, 1060
R_MIN, R_MAX = 130, 470
RING_THICK = 9
BALL_R0, BALL_R_MAX = 15, 21
V_MAX = 2600
SUBSTEPS = 8
G_SCALE = 2000
V0 = 1700
TAIL = 1.0          # seconds shown after escape before the end card
MIN_ESCAPE = 13.0   # keeps total length >= 15 s


@dataclass
class Ring:
    r: float
    gap: float
    a0: float
    w: float
    broken_at: float = None

    def angle(self, t):
        return self.a0 + self.w * t


@dataclass
class Sim:
    rings: list
    frames: list = field(default_factory=list)   # per frame: (t, inner, [(x, y, r)])
    events: list = field(default_factory=list)
    escape_t: float = None


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def simulate(p: dict, seed: int) -> Sim:
    rng = random.Random(seed)
    k = int(p["rings"])
    rings = []
    for i in range(k):
        r = R_MIN + (R_MAX - R_MIN) * (i / (k - 1) if k > 1 else 0)
        direction = 1 if i % 2 == 0 else -1
        rings.append(Ring(r=r,
                          gap=math.radians(p["gap_deg"] * rng.uniform(0.9, 1.1)),
                          a0=rng.uniform(0, 2 * math.pi),
                          w=direction * math.radians(p["spin"]) * (1 + 0.06 * i) * rng.uniform(0.9, 1.1)))
    sim = Sim(rings=rings)
    g = p["gravity"] * G_SCALE
    balls = []
    for _ in range(int(p["balls"])):
        a = rng.uniform(0, 2 * math.pi)
        balls.append([CX + rng.uniform(-25, 25), CY + rng.uniform(-25, 25),
                      V0 * math.cos(a), V0 * math.sin(a), BALL_R0])
    dt = 1 / (C.FPS * SUBSTEPS)
    t, inner, last_note = 0.0, 0, -1.0
    for _ in range(int(p["max_seconds"] * C.FPS)):
        for _ in range(SUBSTEPS):
            t += dt
            for b in balls:
                b[3] += g * dt
                b[0] += b[2] * dt
                b[1] += b[3] * dt
                if inner >= k:
                    continue
                ring = rings[inner]
                dx, dy = b[0] - CX, b[1] - CY
                d = math.hypot(dx, dy) or 1e-6
                edge = ring.r - RING_THICK / 2
                if d + b[4] < edge:
                    continue
                rel = _wrap(math.atan2(dy, dx) - ring.angle(t))
                window = ring.gap / 2 - 0.5 * math.asin(min(1.0, b[4] / ring.r))
                if abs(rel) < window:
                    ring.broken_at = t
                    inner += 1
                    sim.events.append((t, "break"))
                    if inner == k:
                        sim.escape_t = t
                        sim.events.append((t, "win"))
                    continue
                nx, ny = dx / d, dy / d
                vn = b[2] * nx + b[3] * ny
                if vn > 0:
                    b[2] -= 2 * vn * nx
                    b[3] -= 2 * vn * ny
                    jit = rng.uniform(-0.04, 0.04)
                    c, s = math.cos(jit), math.sin(jit)
                    b[2], b[3] = b[2] * c - b[3] * s, b[2] * s + b[3] * c
                    f = 1 + p["speed_up_per_bounce"]
                    sp = math.hypot(b[2], b[3]) * f
                    if sp > V_MAX:
                        f *= V_MAX / sp
                    b[2] *= f
                    b[3] *= f
                    b[4] = min(BALL_R_MAX, b[4] * (1 + p["grow_per_bounce"]))
                    if t - last_note > 0.06:
                        sim.events.append((t, "bounce"))
                        last_note = t
                kk = (edge - b[4] - 0.5) / d
                b[0], b[1] = CX + dx * kk, CY + dy * kk
        sim.frames.append((t, inner, [(b[0], b[1], b[4]) for b in balls]))
        if sim.escape_t is not None and t >= sim.escape_t + TAIL:
            break
    if sim.escape_t is None:
        sim.events.append((t, "end"))
    return sim


def best_sim(p: dict, seed: int) -> Sim:
    """Deterministically try derived seeds until the escape lands in the target window."""
    hi = p["max_seconds"] - TAIL
    fallback = None
    for k in range(30):
        sim = simulate(p, seed * 1000 + k)
        if sim.escape_t is not None and MIN_ESCAPE <= sim.escape_t <= hi:
            return sim
        if sim.escape_t is None and fallback is None:
            fallback = sim
    return fallback or simulate(p, seed * 1000)


def _particles(seed, ring_i, ring, t_break, color):
    rng = random.Random(seed * 7919 + ring_i)
    out = []
    for _ in range(46):
        a = rng.uniform(0, 2 * math.pi)
        sp = rng.uniform(150, 650)
        out.append((CX + ring.r * math.cos(a), CY + ring.r * math.sin(a),
                    sp * math.cos(a) + rng.uniform(-80, 80), sp * math.sin(a) + rng.uniform(-80, 80),
                    rng.uniform(4, 9), t_break, color))
    return out


def render(config: dict, writer) -> dict:
    p = {**DEFAULTS, **(config.get("params") or {})}
    pal = C.palette_rgb(config)
    seed = int(config.get("seed", 0))
    sim = best_sim(p, seed)
    k = len(sim.rings)
    hook = config.get("hook") or f"Can the ball escape all {k} rings?"
    surf = pygame.Surface((C.W, C.H))
    parts = []
    for i, ring in enumerate(sim.rings):
        if ring.broken_at is not None:
            parts += _particles(seed, i, ring, ring.broken_at, pal[i % len(pal)])
    ball_col = C.WHITE
    accent = pal[0]

    for fi, (t, inner, balls) in enumerate(sim.frames):
        surf.fill(C.BG)
        for i in range(inner, k):
            ring = sim.rings[i]
            a = ring.angle(t)
            C.aa_arc(surf, pal[i % len(pal)], CX, CY, ring.r, RING_THICK, a + ring.gap / 2,
                     a + 2 * math.pi - ring.gap / 2)
        for (x0, y0, vx, vy, r, tb, col) in parts:
            age = t - tb
            if 0 <= age < 0.9:
                x = x0 + vx * age
                y = y0 + vy * age + 600 * age * age
                C.aa_circle(surf, (*col, int(255 * (1 - age / 0.9))), x, y, r * (1 - age / 1.2))
        for back in range(8, 0, -1):
            j = fi - back * 2
            if j < 0:
                continue
            for (x, y, r) in sim.frames[j][2]:
                C.aa_circle(surf, (*C.lighten(accent, 0.2), int(110 * (1 - back / 9))), x, y, r * (1 - back / 12))
        for (x, y, r) in balls:
            C.aa_circle(surf, (*accent, 70), x, y, r + 7)
            C.aa_circle(surf, ball_col, x, y, r)
        C.draw_hook(surf, hook)
        left = k - inner
        status = f"{left} RING{'S' if left != 1 else ''} LEFT" if left else "ESCAPED!"
        C.blit_center(surf, C.text_surface(f"{status}   {t:4.1f}s", 64, C.lighten(accent, 0.25)), C.W / 2, 485)
        writer.write(surf)

    last = surf.copy()
    if sim.escape_t is not None:
        title, sub, result = "ESCAPED!", f"in {sim.escape_t:.1f}s", f"escaped in {sim.escape_t:.1f}s"
    else:
        left = k - sim.frames[-1][1]
        noun = "ring" if left == 1 else "rings"
        title, sub, result = "TIME'S UP!", f"{left} {noun} left", f"time's up, {left} {noun} left"
    n = int(C.END_CARD_SECONDS * C.FPS)
    for i in range(n):
        C.draw_end_card(surf, last, title, sub, accent, i / n)
        writer.write(surf)
    return {"events": sim.events, "result": result}
