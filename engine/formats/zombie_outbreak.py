"""zombie_outbreak: "Will anyone survive?" — a top-down city block, a few zombies vs a crowd of humans.

Humans wander, then sprint away from zombies they can see (sprinting drains stamina, so they slow down).
A zombie that touches a human infects it (the human turns into a zombie a moment later) unless the human
fights back and destroys the zombie (fight_chance). Ends when every human is infected ("HUMANITY LOST"),
every zombie is destroyed ("HUMANS WIN"), or time runs out ("N SURVIVORS").
"""
import colorsys
import math
from dataclasses import dataclass, field

import numpy as np
import pygame
import pygame.gfxdraw

from engine import common as C

NAME = "zombie_outbreak"
PARAM_RANGES = {
    "humans": (40, 150, int),
    "zombies": (1, 5, int),
    "zombie_speed": (0.6, 1.2, float),
    "fight_chance": (0.0, 0.4, float),
    "sight": (120, 300, float),
    "max_seconds": (25, 40, float),
}
DEFAULTS = {"humans": 90, "zombies": 2, "zombie_speed": 0.85, "fight_chance": 0.12, "sight": 200,
            "max_seconds": 34}

LEFT, RIGHT, TOP, BOTTOM = 60, 1020, 580, 1540
R = 9
BASE = 120            # walking speed, px/s
SUBSTEPS = 2
TURN_TIME = 0.6       # seconds an infected human flickers before turning
TAIL = 1.2            # seconds shown after the outcome, before the end card
MIN_END = 13.0
HUMAN, TURNING, ZOMBIE, DEAD = 0, 1, 2, 3
ZOMBIE_COL = (120, 255, 90)


@dataclass
class Sim:
    obstacles: list                               # (x, y, half_size)
    frames: list = field(default_factory=list)    # (t, pos (N,2) float32, state (N,) int8, chases (K,2) int)
    events: list = field(default_factory=list)    # (t, kind, pan)
    marks: list = field(default_factory=list)     # (t, "infect"|"kill", x, y)
    end_t: float = None
    outcome: str = "timeout"                      # lost | won | timeout


def _obstacles(rng):
    obs = []
    for _ in range(200):
        if len(obs) == 6:
            break
        h = rng.uniform(42, 70)
        x, y = rng.uniform(LEFT + 90, RIGHT - 90), rng.uniform(TOP + 90, BOTTOM - 90)
        if all(math.hypot(x - ox, y - oy) > h + oh + 70 for ox, oy, oh in obs):
            obs.append((x, y, h))
    return obs


def _free_point(rng, obs):
    while True:
        x, y = rng.uniform(LEFT + 20, RIGHT - 20), rng.uniform(TOP + 20, BOTTOM - 20)
        if all(math.hypot(x - ox, y - oy) > oh * 1.2 + R + 6 for ox, oy, oh in obs):
            return x, y


def _unit(v):
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, 1e-6)


def simulate(p: dict, seed: int) -> Sim:
    rng = np.random.default_rng(seed)
    obs = _obstacles(rng)
    sim = Sim(obstacles=obs)
    nz, nh = int(p["zombies"]), int(p["humans"])
    n = nz + nh
    pos = np.array([_free_point(rng, obs) for _ in range(n)], dtype=float)
    vel = np.zeros((n, 2))
    heading = rng.uniform(0, 2 * np.pi, n)
    stamina = np.ones(n)
    state = np.full(n, HUMAN, dtype=np.int8)
    state[:nz] = ZOMBIE
    turn_at = np.full(n, np.inf)
    cooldown = np.zeros(n)
    sight = p["sight"]
    zspeed = BASE * 1.5 * p["zombie_speed"]
    ob = np.array([(x, y, h * 1.15 + R) for x, y, h in obs]) if obs else np.zeros((0, 3))
    dt = 1 / (C.FPS * SUBSTEPS)
    t, end_frame = 0.0, None
    max_frames = int(p["max_seconds"] * C.FPS)

    for fi in range(max_frames + int(TAIL * C.FPS) + 1):
        chases = np.zeros((0, 2), dtype=int)
        for _ in range(SUBSTEPS):
            t += dt
            state[(state == TURNING) & (t >= turn_at)] = ZOMBIE
            H = np.flatnonzero(state == HUMAN)
            Z = np.flatnonzero(state == ZOMBIE)
            heading += rng.normal(0, 2.2 * math.sqrt(dt), n)
            wander = np.stack([np.cos(heading), np.sin(heading)], axis=1)
            target = np.zeros((n, 2))
            if len(H):
                if len(Z):
                    diff = pos[H][:, None, :] - pos[Z][None, :, :]
                    d = np.linalg.norm(diff, axis=2) + 1e-6
                    seen = d < sight
                    flee = (diff * np.where(seen, 1 / d ** 2, 0)[..., None]).sum(1)
                    fleeing = seen.any(1)
                    # zombies chase their nearest human if they can see one
                    near = d.argmin(0)
                    dz = d[near, np.arange(len(Z))]
                    chasing = dz < sight * 1.4
                    zdir = _unit(pos[H][near] - pos[Z])
                    target[Z] = np.where(chasing[:, None], zdir * zspeed, wander[Z] * BASE * 0.4)
                    chases = np.stack([Z[chasing], H[near[chasing]]], axis=1)
                else:
                    flee, fleeing = np.zeros((len(H), 2)), np.zeros(len(H), bool)
                hdir = np.where(fleeing[:, None], _unit(flee), wander[H])
                # steer away from the arena walls
                hp = pos[H]
                wall = np.stack([np.clip(1 - (hp[:, 0] - LEFT) / 70, 0, 1) - np.clip(1 - (RIGHT - hp[:, 0]) / 70, 0, 1),
                                 np.clip(1 - (hp[:, 1] - TOP) / 70, 0, 1) - np.clip(1 - (BOTTOM - hp[:, 1]) / 70, 0, 1)],
                                axis=1)
                hdir = _unit(hdir + 1.5 * wall)
                stamina[H] = np.clip(stamina[H] + np.where(fleeing, -0.3, 0.15) * dt, 0, 1)
                speed = np.where(fleeing, BASE * (0.95 + 0.85 * stamina[H]), BASE * 0.5)
                target[H] = hdir * speed[:, None]
            elif len(Z):
                target[Z] = wander[Z] * BASE * 0.4
            target[state == TURNING] = 0
            vel += (target - vel) * min(1.0, 7 * dt)
            vel[state == DEAD] = 0
            pos += vel * dt

            # separation between living agents
            alive = np.flatnonzero(state != DEAD)
            diff = pos[alive][:, None, :] - pos[alive][None, :, :]
            d = np.linalg.norm(diff, axis=2) + np.eye(len(alive)) * 1e6
            overlap = np.clip(2 * R - d, 0, None)
            pos[alive] += (diff / d[..., None] * overlap[..., None] * 0.5).sum(1)
            # obstacles and walls
            for ox, oy, orad in ob:
                v = pos - (ox, oy)
                dist = np.linalg.norm(v, axis=1)
                inside = dist < orad
                if inside.any():
                    pos[inside] = (ox, oy) + v[inside] / np.maximum(dist[inside, None], 1e-6) * orad
            for axis, lo, hi in ((0, LEFT + R, RIGHT - R), (1, TOP + R, BOTTOM - R)):
                out = (pos[:, axis] < lo) | (pos[:, axis] > hi)
                vel[out, axis] *= -0.5
                heading[out] = np.arctan2(vel[out, 1], vel[out, 0])
                pos[:, axis] = np.clip(pos[:, axis], lo, hi)

            # bites and fights
            H = np.flatnonzero(state == HUMAN)
            Z = np.flatnonzero(state == ZOMBIE)
            if end_frame is None and len(H) and len(Z):
                d = np.linalg.norm(pos[H][:, None, :] - pos[Z][None, :, :], axis=2)
                for hi, zi in np.argwhere(d < 2 * R + 2):
                    h, z = H[hi], Z[zi]
                    if state[h] != HUMAN or state[z] != ZOMBIE or cooldown[h] > t or cooldown[z] > t:
                        continue
                    x, y = pos[h]
                    pan = (x - C.W / 2) / (C.W / 2)
                    if rng.random() < p["fight_chance"]:
                        state[z] = DEAD
                        cooldown[h] = t + 0.8
                        sim.events.append((t, "break", pan))
                        sim.marks.append((t, "kill", *pos[z]))
                    else:
                        state[h] = TURNING
                        turn_at[h] = t + TURN_TIME
                        cooldown[z] = t + 0.4
                        sim.events.append((t, "bounce", pan))
                        sim.marks.append((t, "infect", x, y))

        sim.frames.append((t, pos.astype(np.float32), state.copy(), chases))
        if end_frame is None:
            humans = int((state == HUMAN).sum())
            zombies = int(((state == ZOMBIE) | (state == TURNING)).sum())
            if humans == 0 or zombies == 0 or fi + 1 >= max_frames:
                sim.outcome = "lost" if humans == 0 else "won" if zombies == 0 else "timeout"
                sim.end_t = t
                sim.events.append((t, "end" if sim.outcome == "lost" else "win", 0.0))
                end_frame = fi
        elif fi - end_frame >= TAIL * C.FPS:
            break
    return sim


def best_sim(p: dict, seed: int) -> Sim:
    """Deterministic seed search so the outcome lands >= MIN_END; adapts difficulty if it ends too soon."""
    q = dict(p)
    fallback = None
    for attempt in range(4):
        early_lost = early_won = 0
        for k in range(6):
            sim = simulate(q, seed * 1000 + attempt * 100 + k)
            if sim.end_t >= MIN_END:
                if sim.outcome != "timeout":
                    return sim
                fallback = fallback or sim
            elif sim.outcome == "lost":
                early_lost += 1
            else:
                early_won += 1
        if early_lost:
            q["zombie_speed"] = max(0.5, q["zombie_speed"] * 0.85)
        if early_won:
            q["fight_chance"] = q["fight_chance"] * 0.5
    return fallback or simulate(q, seed * 1000)


def _human_color(pal):
    """First palette color that isn't green, so humans never look like zombies."""
    for c in pal:
        h, _, s = colorsys.rgb_to_hls(*(v / 255 for v in c))
        if s > 0.3 and not 0.2 < h < 0.47:
            return c
    return (77, 210, 255)


def _arena(bg, obs, seed):
    surf = bg.copy()
    for x in range(LEFT, RIGHT + 1, 120):
        pygame.draw.line(surf, (30, 32, 52), (x, TOP), (x, BOTTOM), 2)
    for y in range(TOP, BOTTOM + 1, 120):
        pygame.draw.line(surf, (30, 32, 52), (LEFT, y), (RIGHT, y), 2)
    pygame.draw.rect(surf, (60, 64, 100), (LEFT - 6, TOP - 6, RIGHT - LEFT + 12, BOTTOM - TOP + 12), 4,
                     border_radius=18)
    rng = np.random.default_rng(seed + 5)
    for x, y, h in obs:
        rect = pygame.Rect(int(x - h), int(y - h), int(2 * h), int(2 * h))
        pygame.draw.rect(surf, (24, 26, 42), rect, border_radius=20)
        pygame.draw.rect(surf, (74, 78, 120), rect, 3, border_radius=20)
        for wx in range(rect.left + 18, rect.right - 16, 22):
            for wy in range(rect.top + 18, rect.bottom - 16, 22):
                lit = rng.random() < 0.35
                pygame.draw.rect(surf, (255, 205, 120) if lit else (40, 42, 64), (wx, wy, 8, 8), border_radius=2)
    return surf


def render(config: dict, writer) -> dict:
    p = {**DEFAULTS, **(config.get("params") or {})}
    pal = C.palette_rgb(config)
    seed = int(config.get("seed", 0))
    sim = best_sim(p, seed)
    hook = config.get("hook") or "Will anyone survive the outbreak?"
    hcol = _human_color(pal)
    bg = C.background(hcol, seed % 7)
    static = _arena(bg, sim.obstacles, seed)
    glow = C.Glow(static, 0.9)
    scene = pygame.Surface((C.W, C.H))
    frame = pygame.Surface((C.W, C.H))
    bursts = [(t, C.make_burst(seed * 11 + i, x, y,
                               [ZOMBIE_COL, C.WHITE] if kind == "infect" else [C.WHITE, (255, 80, 80), hcol],
                               n=14 if kind == "infect" else 36, speed=(80, 300) if kind == "infect" else (150, 600),
                               life=0.4 if kind == "infect" else 0.6, size=(2, 5) if kind == "infect" else (3, 7)))
              for i, (t, kind, x, y) in enumerate(sim.marks)]
    prev_counts, pop_h, pop_z = None, -9.0, -9.0

    for fi, (t, pos, state, chases) in enumerate(sim.frames):
        prev = sim.frames[max(0, fi - 1)][1]
        humans = int((state == HUMAN).sum())
        zombies = int(((state == ZOMBIE) | (state == TURNING)).sum())
        if prev_counts and humans != prev_counts[0]:
            pop_z = t
        if prev_counts and zombies < prev_counts[1]:
            pop_h = t
        prev_counts = (humans, zombies)

        scene.blit(static, (0, 0))
        for z, h in chases:
            pygame.gfxdraw.line(scene, int(pos[z][0]), int(pos[z][1]), int(pos[h][0]), int(pos[h][1]),
                                (*ZOMBIE_COL, 45))
        for t0, parts in bursts:
            if 0 <= t - t0 < 0.7:
                C.draw_burst(scene, parts, t - t0, gravity=300)
        for i in np.flatnonzero(state == HUMAN):
            x, y = pos[i]
            if humans <= 3:
                C.aa_circle(scene, (*hcol, 60), x, y, R + 9 + 4 * math.sin(t * 10))
            C.aa_circle(scene, hcol, x, y, R)
            C.aa_circle(scene, C.lighten(hcol, 0.6), x - 2.5, y - 2.5, 3)
        for i in np.flatnonzero(state == TURNING):
            x, y = pos[i]
            c = ZOMBIE_COL if int(t * 16) % 2 else hcol
            C.aa_circle(scene, (*ZOMBIE_COL, 80), x, y, R + 7)
            C.aa_circle(scene, c, x, y, R + 1)
        for i in np.flatnonzero(state == ZOMBIE):
            x, y = pos[i]
            vx, vy = x - prev[i][0], y - prev[i][1]
            norm = math.hypot(vx, vy) or 1.0
            ux, uy = vx / norm, vy / norm
            C.aa_circle(scene, (*ZOMBIE_COL, 70), x, y, R + 6)
            C.aa_circle(scene, C.mix(ZOMBIE_COL, (30, 70, 30), 0.25), x, y, R + 1)
            for side in (-1, 1):
                C.aa_circle(scene, (255, 50, 50), x + ux * 4 - uy * 3.5 * side, y + uy * 4 + ux * 3.5 * side, 2)
        glow.apply(scene)

        shake, fl = 0.0, None
        if sim.end_t is not None and t >= sim.end_t:
            age = t - sim.end_t
            shake = 14 * math.exp(-age / 0.1)
            fl = ((255, 40, 40) if sim.outcome == "lost" else C.WHITE, 100 * math.exp(-age / 0.15))
        C.shaken(frame, scene, shake, t, seed % 97)
        if fl:
            C.flash(frame, *fl)

        C.draw_hook(frame, hook)
        C.pop_text(frame, f"HUMANS {humans}", 56, hcol, 250, 470, math.exp(-(t - pop_h) / 0.12) * 0.5)
        C.pop_text(frame, f"ZOMBIES {zombies}", 56, ZOMBIE_COL, 830, 470, math.exp(-(t - pop_z) / 0.12) * 0.5)
        C.blit_center(frame, C.text_surface(f"{min(t, sim.end_t or t):4.1f}s", 44, C.WHITE, 3), C.W / 2, 470)
        frac = humans / max(1, humans + zombies)
        bar = pygame.Rect(90, 515, 900, 22)
        pygame.draw.rect(frame, ZOMBIE_COL, bar, border_radius=11)
        if frac > 0:
            pygame.draw.rect(frame, hcol, (bar.x, bar.y, max(22, int(bar.w * frac)), bar.h), border_radius=11)
        writer.write(frame)

    last = frame.copy()
    survivors = int((sim.frames[-1][2] == HUMAN).sum())
    noun = "survivor" if survivors == 1 else "survivors"
    confetti = None
    if sim.outcome == "lost":
        title, sub, accent = "HUMANITY LOST", f"in {sim.end_t:.1f}s", ZOMBIE_COL
        result = f"humanity lost in {sim.end_t:.1f}s"
    elif sim.outcome == "won":
        title, sub, accent = "HUMANS WIN!", f"{survivors} {noun}", hcol
        result = f"humans win, {survivors} {noun}"
        confetti = C.make_confetti(seed, [hcol, C.WHITE, (255, 205, 120)])
    else:
        title, sub, accent = f"{survivors} {noun.upper()}", "made it to the end", hcol
        result = f"{survivors} {noun} at time's up"
        confetti = C.make_confetti(seed, [hcol, C.WHITE, (255, 205, 120)])
    nf = int(C.END_CARD_SECONDS * C.FPS)
    for i in range(nf):
        C.draw_end_card(frame, last, title, sub, accent, i / nf, confetti)
        writer.write(frame)
    return {"events": sim.events, "result": result}
