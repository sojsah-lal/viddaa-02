"""Schema check + clamp ranges + fallback preset. The only gate between the LLM and the engine."""
import json
import random
import re
from pathlib import Path

from engine.formats import FORMATS
from engine.melodies import MELODIES

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ROOT / "presets"
TOP_KEYS = ("format", "seed", "hook", "caption", "hashtags", "palette", "melody", "params")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Invalid(ValueError):
    pass


def clamp_params(fmt: str, params) -> dict:
    ranges = FORMATS[fmt].PARAM_RANGES
    out = {}
    for key, value in (params or {}).items():
        if key not in ranges:
            continue
        lo, hi, typ = ranges[key]
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise Invalid(f"param {key!r} is not a number: {value!r}")
        v = min(hi, max(lo, v))
        out[key] = int(round(v)) if typ is int else round(v, 4)
    return out


def sanitize(raw: dict) -> dict:
    """Return a clean config or raise Invalid."""
    if not isinstance(raw, dict):
        raise Invalid("config is not an object")
    cfg = {k: raw[k] for k in TOP_KEYS if k in raw}
    fmt = cfg.get("format")
    if fmt not in FORMATS:
        raise Invalid(f"unknown format {fmt!r}")
    try:
        cfg["seed"] = int(cfg.get("seed", random.randrange(1, 2**31))) % 2**31
    except (TypeError, ValueError):
        raise Invalid("seed is not an integer")

    hook = cfg.get("hook")
    if not isinstance(hook, str) or not hook.strip():
        raise Invalid("hook missing")
    if len(hook) > 60:
        raise Invalid(f"hook too long ({len(hook)} chars)")
    cfg["hook"] = hook.strip()

    caption = cfg.get("caption", "")
    if not isinstance(caption, str) or len(caption) > 2000:
        raise Invalid("caption missing or longer than 2000 chars")

    tags = cfg.get("hashtags") or []
    if not isinstance(tags, list):
        raise Invalid("hashtags is not a list")
    cfg["hashtags"] = [re.sub(r"[^\w]", "", str(t).lstrip("#")) for t in tags if str(t).strip("# ")][:5]

    pal = cfg.get("palette")
    if not isinstance(pal, list) or not 3 <= len(pal) <= 8 or not all(isinstance(c, str) and HEX.match(c) for c in pal):
        raise Invalid(f"palette must be 3-8 #RRGGBB colors, got {pal!r}")

    if cfg.get("melody") not in MELODIES:
        raise Invalid(f"unknown melody {cfg.get('melody')!r}")

    cfg["params"] = {**FORMATS[fmt].DEFAULTS, **clamp_params(fmt, cfg.get("params"))}
    return cfg


def presets_for(fmt: str = None) -> list:
    files = sorted(PRESETS.glob("*.json"))
    if fmt:
        files = [f for f in files if f.stem.rsplit("_", 1)[0] == fmt]
    return files


def fallback(rng: random.Random, avoid_format: str = None, only_format: str = None) -> dict:
    """Random preset (different format from the last run unless forced), with a fresh seed."""
    if only_format:
        files = presets_for(only_format)
    else:
        files = [f for f in presets_for() if f.stem.rsplit("_", 1)[0] != avoid_format] or presets_for()
    cfg = json.loads(rng.choice(files).read_text(encoding="utf-8"))
    cfg["seed"] = rng.randrange(1, 2**31)
    return sanitize(cfg)


def validate(raw, rng: random.Random, last_format: str = None, only_format: str = None):
    """Returns (config, problem). problem is None when raw was accepted."""
    try:
        cfg = sanitize(raw)
        if only_format and cfg["format"] != only_format:
            raise Invalid(f"format {cfg['format']!r} but {only_format!r} was requested")
        return cfg, None
    except Invalid as e:
        print(f"[validate] rejected config: {e} -> using a fallback preset")
        return fallback(rng, avoid_format=last_format, only_format=only_format), str(e)
