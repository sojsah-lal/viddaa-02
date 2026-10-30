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
    break_xy: tuple = None

    def angle(self, t):
        return self.a0 + self.w * t


@dataclass
class Sim:
    rings: list
    frames: list = field(default_factory=list)   # per frame: (t, inner, [(x, y, r, color_index)])
    events: list = field(default_factory=list)   # (t, kind, pan)
    hits: list = field(default_factory=list)     # (t, ring_index, x, y)
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
                      V0 * math.cos(a), V0 * math.sin(a), BALL_R0, -1])  # last: color index of last ring hit
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
                pan = dx / R_MAX
                if abs(rel) < window:
                    ring.broken_at = t
                    ring.break_xy = (b[0], b[1])
                    b[5] = inner
                    inner += 1
                    sim.events.append((t, "break", pan))
                    if inner == k:
                        sim.escape_t = t
                        sim.events.append((t, "win", pan))
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
                    b[5] = inner
                    sim.hits.append((t, inner, CX + nx * edge, CY + ny * edge))
                    if t - last_note > 0.06:
                        sim.events.append((t, "bounce", pan))
                        last_note = t
                kk = (edge - b[4] - 0.5) / d
                b[0], b[1] = CX + dx * kk, CY + dy * kk
        sim.frames.append((t, inner, [(b[0], b[1], b[4], b[5]) for b in balls]))
        if sim.escape_t is not None and t >= sim.escape_t + TAIL:
            break
    if sim.escape_t is None:
        sim.events.append((t, "end", 0.0))
    return sim


def best_sim(p: dict, seed: int) -> Sim:
    """Deterministically try derived seeds until the escape lands in the target window."""
    hi = p["max_seconds"] - TAIL
    q = dict(p)
    timeout = slowest = None
    for attempt in range(5):
        fast = 0
        for k in range(30):
            sim = simulate(q, seed * 1000 + attempt * 100 + k)
            if sim.escape_t is None:
                timeout = timeout or sim
            elif MIN_ESCAPE <= sim.escape_t <= hi:
                return sim
            elif sim.escape_t < MIN_ESCAPE:
                fast += 1
                if slowest is None or sim.escape_t > slowest.escape_t:
                    slowest = sim
        # every try escaped too fast -> make it harder; otherwise easier
        q["gap_deg"] = max(18.0, q["gap_deg"] * 0.8) if fast >= 15 else min(80.0, q["gap_deg"] * 1.2)
    return timeout or slowest


def _shards(seed, i, ring, color):
    """The broken ring splits into spinning arc fragments that fly out and fall."""
    rng = random.Random(seed * 7919 + i)
    n = 16
    span = 2 * math.pi / n
    base = ring.angle(ring.broken_at)
    return [(base + j * span + rng.uniform(-0.1, 0.1), span * rng.uniform(0.45, 0.8), rng.uniform(140, 460),
             rng.uniform(-2.5, 2.5), rng.uniform(0.7, 1.1), color) for j in range(n)]


def _shake(sim, t):
    amp = 0.0
    for ring in sim.rings:
        if ring.broken_at is not None and 0 <= t - ring.broken_at < 0.4:
            big = 26 if ring.broken_at == sim.escape_t else 11
            amp += big * math.exp(-(t - ring.broken_at) / 0.07)
    return amp


def render(config: dict, writer) -> dict:
    p = {**DEFAULTS, **(config.get("params") or {})}
    pal = C.palette_rgb(config)
    seed = int(config.get("seed", 0))
    sim = best_sim(p, seed)
    k = len(sim.rings)
    hook = config.get("hook") or f"Can the ball escape all {k} rings?"
    accent = pal[0]
    bg = C.background(accent, seed % 7)
    glow = C.Glow(bg)
    scene = pygame.Surface((C.W, C.H))
    frame = pygame.Surface((C.W, C.H))
    col = lambda i: pal[i % len(pal)]

    shards, bursts = [], []
    for i, ring in enumerate(sim.rings):
        if ring.broken_at is not None:
            shards.append((ring, _shards(seed, i, ring, col(i))))
            bx, by = ring.break_xy
            bursts.append((ring.broken_at, C.make_burst(seed * 31 + i, bx, by, [col(i), C.WHITE], n=40,
                                                        speed=(200, 700), life=0.6, size=(4, 8))))
    for hi, (ht, ri, hx, hy) in enumerate(sim.hits):
        bursts.append((ht, C.make_burst(seed * 131 + hi, hx, hy, [col(ri), C.WHITE], n=9,
                                        speed=(90, 320), life=0.3, size=(2, 4))))
    bursts.sort(key=lambda b: b[0])

    last_hit = [-9.0] * k
    hit_ptr = 0
    for fi, (t, inner, balls) in enumerate(sim.frames):
        while hit_ptr < len(sim.hits) and sim.hits[hit_ptr][0] <= t:
            last_hit[sim.hits[hit_ptr][1]] = sim.hits[hit_ptr][0]
            hit_ptr += 1
        broke = [r.broken_at for r in sim.rings if r.broken_at is not None and r.broken_at <= t]
        since_break = t - max(broke) if broke else 9.0
        pop = math.exp(-since_break / 0.12)

        scene.blit(bg, (0, 0))
        left = k - inner
        if left:
            C.pop_text(scene, str(left), 260, C.WHITE, CX, CY, pop, alpha=int(38 + 60 * pop), stroke=0)
        for i in range(inner, k):
            ring = sim.rings[i]
            a = ring.angle(t)
            h = max(0.0, 1 - (t - last_hit[i]) / 0.15)
            C.aa_arc(scene, C.mix(col(i), C.WHITE, 0.7 * h), CX, CY, ring.r, RING_THICK + 6 * h,
                     a + ring.gap / 2, a + 2 * math.pi - ring.gap / 2)
        for ring, parts in shards:
            age = t - ring.broken_at
            for (a0, span, vr, spin, life, c) in parts:
                if not 0 <= age < life:
                    continue
                f = 1 - age / life
                a = a0 + ring.w * ring.broken_at + spin * age
                C.aa_arc(scene, (*C.lighten(c, 0.25 * f), int(255 * f)), CX, CY + 700 * age * age,
                         ring.r + vr * age, max(2.0, RING_THICK * f), a, a + span * (0.5 + 0.5 * f))
        for t0, parts in bursts:
            if t0 > t:
                break
            if t - t0 < 0.8:
                C.draw_burst(scene, parts, t - t0)
        for bi, (x, y, r, ci) in enumerate(balls):
            c = col(ci) if ci >= 0 else C.WHITE
            pts = [(f[2][bi][0], f[2][bi][1]) for f in sim.frames[max(0, fi - 9):fi + 1]]
            C.draw_trail(scene, pts, c, r * 0.9)
            C.aa_circle(scene, (*c, 90), x, y, r + 10)
            C.aa_circle(scene, C.mix(c, C.WHITE, 0.65), x, y, r)
        glow.apply(scene)

        C.shaken(frame, scene, _shake(sim, t), t, seed % 97)
        if sim.escape_t is not None and t >= sim.escape_t:
            C.flash(frame, C.WHITE, 110 * math.exp(-(t - sim.escape_t) / 0.08))
        elif broke:
            C.flash(frame, col(inner - 1), 45 * math.exp(-since_break / 0.08))
        C.draw_hook(frame, hook)
        status = f"{left} RING{'S' if left != 1 else ''} LEFT" if left else "ESCAPED!"
        C.pop_text(frame, f"{status}   {t:4.1f}s", 64, C.lighten(accent, 0.25), C.W / 2, 485, pop * 0.4)
        writer.write(frame)

    last = frame.copy()
    confetti = None
    if sim.escape_t is not None:
        title, sub, result = "ESCAPED!", f"in {sim.escape_t:.1f}s", f"escaped in {sim.escape_t:.1f}s"
        confetti = C.make_confetti(seed, pal)
    else:
        left = k - sim.frames[-1][1]
        noun = "ring" if left == 1 else "rings"
        title, sub, result = "TIME'S UP!", f"{left} {noun} left", f"time's up, {left} {noun} left"
    n = int(C.END_CARD_SECONDS * C.FPS)
    for i in range(n):
        C.draw_end_card(frame, last, title, sub, accent, i / n, confetti)
        writer.write(frame)
    return {"events": sim.events, "result": result}
