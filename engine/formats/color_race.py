"""color_race: "Which color wins?" — Plinko-style race down a tall peg board, camera follows the leader.

`balls` colored balls (named by color: RED, BLUE, ...) drop through pegs to a finish line;
the first across wins and the video ends with "<COLOR> WINS".
"""
import colorsys
import math
import random
from dataclasses import dataclass, field

import pygame

from engine import common as C

NAME = "color_race"
PARAM_RANGES = {
    "balls": (4, 6, int),
    "course_length": (3000, 5000, float),
    "peg_spacing": (85, 115, float),
    "gravity": (0.3, 0.9, float),
    "restitution": (0.4, 0.8, float),
    "max_seconds": (25, 40, float),
}
DEFAULTS = {"balls": 5, "course_length": 4200, "peg_spacing": 96, "gravity": 0.5,
            "restitution": 0.6, "max_seconds": 38}

LEFT, RIGHT = 70, 1010
START_Y = 80
PEG_TOP = 260
BALL_R, PEG_R = 22, 9
PLAY_TOP = 540          # screen y where the world view begins
FINISH_SCREEN = 1440    # finish line never drawn below this screen y
RELEASE_T = 1.0
TAIL = 1.5
SUBSTEPS = 8
NOTE_GAP = 0.08
MIN_WIN = 13.0

COLOR_NAMES = [(0, "RED"), (25, "ORANGE"), (52, "YELLOW"), (110, "GREEN"), (180, "CYAN"),
               (215, "BLUE"), (275, "PURPLE"), (320, "PINK"), (360, "RED")]


def color_name(rgb) -> str:
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    if s < 0.2:
        return "WHITE" if l > 0.6 else "GRAY"
    deg = h * 360
    return min(COLOR_NAMES, key=lambda c: abs(c[0] - deg))[1]


def ball_names(colors) -> list:
    names, seen = [], {}
    for c in colors:
        n = color_name(c)
        seen[n] = seen.get(n, 0) + 1
        names.append(n if seen[n] == 1 else f"{n} {seen[n]}")
    return names


@dataclass
class Sim:
    pegs: list
    rows: dict
    finish: float
    frames: list = field(default_factory=list)   # (t, [(x, y)], [peg ids hit this frame])
    events: list = field(default_factory=list)
    winner: int = None
    win_t: float = None


def build_pegs(p, rng):
    sp = p["peg_spacing"]
    row_h = sp * 0.82
    pegs, rows = [], {}
    y, j = PEG_TOP, 0
    while y < p["course_length"] - 160:
        x = LEFT + sp / 2 + (sp / 2 if j % 2 else 0)
        while x < RIGHT - sp / 3:
            px = x + rng.uniform(-6, 6)
            r = PEG_R * (2.2 if rng.random() < 0.05 else 1)
            rows.setdefault(j, []).append(len(pegs))
            pegs.append((px, y, r))
            x += sp
        y += row_h
        j += 1
    return pegs, rows, row_h


def simulate(p, seed, colors_n) -> Sim:
    rng = random.Random(seed)
    pegs, rows, row_h = build_pegs(p, rng)
    finish = p["course_length"]
    sim = Sim(pegs=pegs, rows=rows, finish=finish)
    g = p["gravity"] * 2000
    e = p["restitution"]
    n = colors_n
    gapx = (RIGHT - LEFT) / (n + 1)
    balls = [[LEFT + gapx * (i + 1) + rng.uniform(-8, 8), START_Y, 0.0, 0.0] for i in range(n)]
    order = list(range(n))
    rng.shuffle(order)
    balls = [balls[i] for i in order]
    still = [0.0] * n
    finished = [False] * n
    dt = 1 / (C.FPS * SUBSTEPS)
    t, last_note = 0.0, -1.0
    floor = finish + 260

    def note():
        nonlocal last_note
        if t - last_note >= NOTE_GAP:
            sim.events.append((t, "bounce"))
            last_note = t

    for _ in range(int(p["max_seconds"] * C.FPS)):
        hits = []
        for _ in range(SUBSTEPS):
            t += dt
            if t < RELEASE_T:
                continue
            for bi, b in enumerate(balls):
                b[3] += g * dt
                b[0] += b[2] * dt
                b[1] += b[3] * dt
                # walls
                if b[0] < LEFT + BALL_R:
                    b[0] = LEFT + BALL_R
                    if b[2] < 0:
                        b[2] = -b[2] * e
                        note()
                elif b[0] > RIGHT - BALL_R:
                    b[0] = RIGHT - BALL_R
                    if b[2] > 0:
                        b[2] = -b[2] * e
                        note()
                if b[1] > floor - BALL_R:
                    b[1] = floor - BALL_R
                    b[3] = -abs(b[3]) * 0.3
                    b[2] *= 0.9
                # pegs (only nearby rows)
                jr = int((b[1] - PEG_TOP) / row_h)
                for j in (jr - 1, jr, jr + 1):
                    for pid in rows.get(j, ()):
                        px, py, pr = pegs[pid]
                        dx, dy = b[0] - px, b[1] - py
                        dist2 = dx * dx + dy * dy
                        rr = pr + BALL_R
                        if dist2 >= rr * rr:
                            continue
                        d = math.sqrt(dist2) or 1e-6
                        nx, ny = dx / d, dy / d
                        b[0], b[1] = px + nx * rr, py + ny * rr
                        vn = b[2] * nx + b[3] * ny
                        if vn < 0:
                            b[2] -= (1 + e) * vn * nx
                            b[3] -= (1 + e) * vn * ny
                            b[2] += rng.uniform(-18, 18)
                            hits.append(pid)
                            note()
            # ball-ball elastic
            if t >= RELEASE_T:
                for i in range(n):
                    for j in range(i + 1, n):
                        a, b = balls[i], balls[j]
                        dx, dy = b[0] - a[0], b[1] - a[1]
                        d2 = dx * dx + dy * dy
                        if d2 >= (2 * BALL_R) ** 2 or d2 == 0:
                            continue
                        d = math.sqrt(d2)
                        nx, ny = dx / d, dy / d
                        overlap = 2 * BALL_R - d
                        a[0] -= nx * overlap / 2
                        a[1] -= ny * overlap / 2
                        b[0] += nx * overlap / 2
                        b[1] += ny * overlap / 2
                        rel = (a[2] - b[2]) * nx + (a[3] - b[3]) * ny
                        if rel > 0:
                            a[2] -= rel * nx
                            a[3] -= rel * ny
                            b[2] += rel * nx
                            b[3] += rel * ny
                            note()
            for bi, b in enumerate(balls):
                if not finished[bi] and b[1] >= finish:
                    finished[bi] = True
                    if sim.winner is None:
                        sim.winner, sim.win_t = bi, t
                        sim.events.append((t, "win"))
        # stuck detection, once per frame
        if t >= RELEASE_T:
            for bi, b in enumerate(balls):
                if finished[bi]:
                    continue
                if math.hypot(b[2], b[3]) < 20:
                    still[bi] += 1 / C.FPS
                    if still[bi] >= 1.0:
                        b[2] += rng.choice((-1, 1)) * 260
                        b[3] -= 120
                        still[bi] = 0
                else:
                    still[bi] = 0
        sim.frames.append((t, [(b[0], b[1]) for b in balls], hits))
        if sim.win_t is not None and t >= sim.win_t + TAIL:
            break
    if sim.winner is None:
        sim.winner = max(range(n), key=lambda i: balls[i][1])
        sim.events.append((t, "end"))
    return sim


def best_sim(p, seed, n) -> Sim:
    hi = p["max_seconds"] - TAIL
    first = None
    for k in range(30):
        sim = simulate(p, seed * 1000 + k, n)
        first = first or sim
        if sim.win_t is not None and MIN_WIN <= sim.win_t <= hi:
            return sim
    return first


def _draw_finish(surf, y):
    sq = 30
    for i, x in enumerate(range(LEFT, RIGHT, sq)):
        for r in range(2):
            col = C.WHITE if (i + r) % 2 == 0 else (20, 20, 28)
            pygame.draw.rect(surf, col, (x, int(y) + r * sq - sq, sq, sq))


def render(config: dict, writer) -> dict:
    p = {**DEFAULTS, **(config.get("params") or {})}
    pal = C.palette_rgb(config)
    n = int(p["balls"])
    colors = [pal[i % len(pal)] for i in range(n)]
    names = ball_names(colors)
    seed = int(config.get("seed", 0))
    sim = best_sim(p, seed, n)
    hook = config.get("hook") or "Which color wins? Comment before it ends!"
    surf = pygame.Surface((C.W, C.H))
    peg_glow = [-9.0] * len(sim.pegs)
    peg_col = (70, 72, 96)
    cam_max = sim.finish - (FINISH_SCREEN - PLAY_TOP)
    cam = 0.0

    for fi, (t, balls, hits) in enumerate(sim.frames):
        for pid in hits:
            peg_glow[pid] = t
        lead = max(range(n), key=lambda i: balls[i][1])
        target = min(cam_max, max(0.0, balls[lead][1] - 520))
        cam += (target - cam) * 0.1
        ys = lambda wy: wy - cam + PLAY_TOP

        surf.fill(C.BG)
        pygame.draw.rect(surf, (32, 34, 48), (LEFT - 8, PLAY_TOP, 8, C.H))
        pygame.draw.rect(surf, (32, 34, 48), (RIGHT, PLAY_TOP, 8, C.H))
        for (px, py, pr), glow_t in zip(sim.pegs, peg_glow):
            sy = ys(py)
            if sy < PLAY_TOP - 30 or sy > C.H + 30:
                continue
            k = max(0.0, 1 - (t - glow_t) / 0.35)
            col = tuple(int(a + (b - a) * k) for a, b in zip(peg_col, C.WHITE))
            C.aa_circle(surf, col, px, sy, pr + 3 * k)
        if ys(sim.finish) < C.H + 40:
            _draw_finish(surf, ys(sim.finish))
        for back in range(6, 0, -1):
            j = fi - back * 2
            if j < 0:
                continue
            for i, (x, y) in enumerate(sim.frames[j][1]):
                C.aa_circle(surf, (*colors[i], int(90 * (1 - back / 7))), x, ys(y), BALL_R * (1 - back / 10))
        for i, (x, y) in enumerate(balls):
            C.aa_circle(surf, colors[i], x, ys(y), BALL_R)
            C.aa_circle(surf, C.lighten(colors[i], 0.6), x - 7, ys(y) - 7, 6)

        # header band + live state
        pygame.draw.rect(surf, C.BG, (0, 0, C.W, PLAY_TOP))
        C.draw_hook(surf, hook)
        if t < RELEASE_T:
            label, col = "READY...", C.WHITE
        elif t < RELEASE_T + 0.6:
            label, col = "GO!", C.WHITE
        else:
            label, col = f"LEADER: {names[lead]}", colors[lead]
        C.blit_center(surf, C.text_surface(label, 68, col), C.W / 2, 480)
        # progress strip
        pygame.draw.rect(surf, (40, 42, 58), (1040, 560, 6, 880))
        for i, (x, y) in enumerate(balls):
            frac = min(1.0, max(0.0, (y - START_Y) / (sim.finish - START_Y)))
            C.aa_circle(surf, colors[i], 1043, 560 + 880 * frac, 10)
        writer.write(surf)

    last = surf.copy()
    win_name = names[sim.winner]
    sub = f"in {sim.win_t:.1f}s" if sim.win_t is not None else "closest to the finish"
    nf = int(C.END_CARD_SECONDS * C.FPS)
    for i in range(nf):
        C.draw_end_card(surf, last, f"{win_name} WINS", sub, colors[sim.winner], i / nf)
        writer.write(surf)
    return {"events": sim.events, "result": f"{win_name.lower()} wins", "winner": win_name}
