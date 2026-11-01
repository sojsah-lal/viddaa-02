"""history + format list -> LLM (or preset variation) -> raw config."""
import json
import os
import random
import re
import shutil
import subprocess
import time

import requests

from engine.formats import FORMATS
from engine.melodies import MELODIES
from planner.validate import presets_for

HOOKS = {
    "escape_rings": [  # {{X}} = deadline seconds, filled in by the engine
        "Will it escape in {{X}} seconds?",
        "{rings} rings. {{X}} seconds. Can it escape?",
        "Escape all {rings} rings in {{X}}s? 👇",
        "Bet it can't escape in {{X}} seconds",
        "{{X}} seconds on the clock. Will it make it?",
        "Yes or no: out in {{X}} seconds? 👇",
    ],
    "color_race": [
        "Which color wins? Pick one 👇",
        "{balls} colors. 1 winner. Pick now!",
        "Comment your color before it ends!",
        "Who wins this race? 👇",
        "Pick a color. Prove you're lucky.",
        "Your color vs the rest. Pick fast!",
    ],
    "zombie_outbreak": [
        "Will anyone survive the outbreak?",
        "{zombies} zombies vs {humans} humans. Bet?",
        "Humans or zombies? Pick a side 👇",
        "How long can {humans} humans last?",
        "One bite and it spreads. Survivors?",
        "Can the humans fight back in time?",
    ],
}
CAPTIONS = {
    "escape_rings": ["It was SO close 😳", "Watch till the end 👀", "Did you guess the time? 👇",
                     "The last ring though... 😮‍💨"],
    "color_race": ["Comment your color before it ends! 🏁", "Which one did you pick? 👇",
                   "Rematch tomorrow 🔁", "No way it won that 😳"],
    "zombie_outbreak": ["Humans or zombies? Comment before it ends 🧟", "That last survivor though 😳",
                        "Would you have made it? 👇", "It spreads SO fast 😱"],
}
TAGS = {
    "escape_rings": ["satisfying", "physics", "simulation", "oddlysatisfying", "asmr"],
    "color_race": ["marblerace", "satisfying", "plinko", "simulation", "race"],
    "zombie_outbreak": ["zombie", "simulation", "zombieapocalypse", "satisfying", "survival"],
}
PALETTES = [
    ["#FF4D6D", "#4DD2FF", "#FFD24D", "#7CFF4D", "#C77DFF", "#FF9F1C"],
    ["#F72585", "#7209B7", "#4CC9F0", "#FFD60A", "#06D6A0", "#FF8500"],
    ["#FF595E", "#FFCA3A", "#8AC926", "#1982C4", "#6A4C93", "#FF924C"],
    ["#00F5D4", "#FEE440", "#F15BB5", "#9B5DE5", "#00BBF9", "#FF6B35"],
    ["#E63946", "#2EC4B6", "#FFBE0B", "#3A86FF", "#B5179E", "#80ED99"],
]
HOOK_RULES = (
    "Hook rules: a question or challenge, ideally 8 words or fewer, max 60 characters; creates suspense "
    "about the ending; invites a comment (e.g. 'Pick a color 👇'); no clickbait lies; no real people or brands. "
    "If the hook mentions a number (rings, colors), it must match params. Only promise what the format "
    "description says can happen."
)


def choose_format(history: list, rng: random.Random, forced: str = None) -> str:
    if forced:
        return forced
    last = history[-1]["format"] if history else None
    options = [f for f in FORMATS if f != last] or list(FORMATS)
    return rng.choice(options)


def recent(history, key, n=14):
    return [h.get(key) for h in history[-n:] if h.get(key)]


def preset_variation(fmt: str, rng: random.Random, history: list) -> dict:
    """No-LLM path: a preset with a new seed, jittered params, fresh hook/palette/melody."""
    cfg = json.loads(rng.choice(presets_for(fmt)).read_text(encoding="utf-8"))
    ranges = FORMATS[fmt].PARAM_RANGES
    params = {**FORMATS[fmt].DEFAULTS, **cfg.get("params", {})}
    for k, (lo, hi, typ) in ranges.items():
        if k == "max_seconds":
            continue
        v = params[k] + rng.uniform(-0.15, 0.15) * (hi - lo)
        v = min(hi, max(lo, v))
        params[k] = int(round(v)) if typ is int else round(v, 3)
    recent_hooks = set(recent(history, "hook"))
    hooks = [h.format(**params) for h in HOOKS[fmt]]
    fresh = [h for h in hooks if h not in recent_hooks] or hooks
    recent_pals = [tuple(p) for p in recent(history, "palette", 3)]
    pals = [p for p in PALETTES if tuple(p) not in recent_pals] or PALETTES
    pal = list(rng.choice(pals))
    rng.shuffle(pal)
    recent_mel = set(recent(history, "melody", 3))
    mels = [m for m in MELODIES if m not in recent_mel] or list(MELODIES)
    tags = rng.sample(TAGS[fmt], 4)
    return {
        "format": fmt,
        "seed": rng.randrange(1, 2**31),
        "hook": rng.choice(fresh),
        "caption": f"{rng.choice(CAPTIONS[fmt])} " + " ".join(f"#{t}" for t in tags),
        "hashtags": tags,
        "palette": pal,
        "melody": rng.choice(mels),
        "params": params,
    }


def build_prompt(fmt: str, history: list) -> str:
    ranges = {k: [lo, hi] for k, (lo, hi, _) in FORMATS[fmt].PARAM_RANGES.items()}
    about = (FORMATS[fmt].__doc__ or "").strip()
    return (
        "You plan one short vertical TikTok video rendered by a fixed physics engine. "
        "Reply with ONLY a JSON object, no prose.\n\n"
        f"Format: {fmt} — {about}\n"
        f"Allowed params with [min, max]: {json.dumps(ranges)}\n"
        f"Melodies (pick one): {list(MELODIES)}\n"
        f"Recent hooks to avoid repeating: {json.dumps(recent(history, 'hook'), ensure_ascii=False)}\n"
        f"Recent palettes to avoid: {json.dumps(recent(history, 'palette', 3))}\n\n"
        f"{HOOK_RULES}\n\n"
        "JSON keys: hook (string), caption (string, 1 short line + hashtags, max 150 chars), "
        "hashtags (3-5 strings without #), palette (4-6 saturated hex colors like #FF4D6D that pop on a "
        "near-black background, all clearly different hues), melody (string), params (object using the "
        "allowed params). Aim for an ending that lands 15-35 seconds in."
    )


def extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return json.loads(m.group(0))


def call_gemini(prompt: str) -> dict:
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0}}
    last = None
    for attempt in range(2):
        try:
            r = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=30)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return extract_json(text)
        except Exception as e:  # network, HTTP, shape or JSON errors all retry once
            last = e
            if attempt == 0:
                time.sleep(3)
    raise RuntimeError(f"gemini failed: {last}")


def call_claude(prompt: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    # Prompt goes over stdin: the Windows claude.cmd shim truncates multi-line arguments.
    exe = shutil.which("claude") or "claude"
    out = subprocess.run([exe, "-p", "--output-format", "json"], input=prompt, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=180)
    if out.returncode != 0:
        raise RuntimeError(f"claude exited {out.returncode}: {out.stderr[-300:]}")
    return extract_json(json.loads(out.stdout)["result"])


def famous_hook(shorts: list) -> str:
    for hook in (" vs ".join(shorts) + ". Pick one 👇",
                 f"{shorts[0]}, {shorts[1]} or {len(shorts) - 2} more? Pick 👇",
                 "Famous faces race. Pick a winner 👇"):
        if len(hook) <= 48:
            return hook
    return "Famous faces race. Pick a winner 👇"


def add_famous(raw: dict, rng: random.Random, history: list) -> bool:
    """On race days, swap colored balls for people trending on Wikipedia (free-licensed photos only).
    Leaves raw untouched (plain colors) if fewer than 4 qualify. Set FAMOUS_FACES=off to disable."""
    if raw.get("format") != "color_race" or (os.environ.get("FAMOUS_FACES") or "on").lower() == "off":
        return False
    from planner import celebs
    recent_people = {name for h in history[-3:] for name in h.get("players") or []}
    pool = celebs.fetch(n_max=10, exclude=recent_people, seed=rng.randrange(2**31))
    if len(pool) < 4:
        print(f"[plan] only {len(pool)} trending people with free photos; using colored balls")
        return False
    n = min(len(pool), max(4, int((raw.get("params") or {}).get("balls", 5))))
    players = pool[:n]
    rng.shuffle(players)  # starting slot shouldn't follow the trending rank
    shorts = [p["short"] for p in players]
    tags = [re.sub(r"[^a-z0-9]", "", p["name"].lower()) for p in players[:2]]
    raw["players"] = players
    raw.setdefault("params", {})["balls"] = n
    raw["hook"] = famous_hook(shorts)
    raw["hashtags"] = [t for t in tags if t] + ["race", "satisfying", "fyp"]
    raw["caption"] = ("Who did you pick? Comment before it ends 👇\n\n"
                      "Photos via Wikimedia Commons: " + "; ".join(p["credit"] for p in players))
    return True


def plan(history: list, rng: random.Random, forced_format: str = None):
    """Returns (raw_config, source)."""
    fmt = choose_format(history, rng, forced_format)
    provider = (os.environ.get("LLM_PROVIDER") or "gemini").lower()
    try:
        if provider == "claude":
            raw, source = call_claude(build_prompt(fmt, history)), "claude"
        elif os.environ.get("GEMINI_API_KEY"):
            raw, source = call_gemini(build_prompt(fmt, history)), "gemini"
        else:
            raw, source = preset_variation(fmt, rng, history), "preset"
    except Exception as e:
        print(f"[plan] LLM step failed ({e}); using preset variation")
        raw, source = preset_variation(fmt, rng, history), "preset"
    raw["format"] = fmt
    raw["seed"] = rng.randrange(1, 2**31)
    if add_famous(raw, rng, history):
        source += "+famous"
    return raw, source
