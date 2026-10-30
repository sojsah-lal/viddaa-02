"""FORMAT registry: name -> module.

Each format module exposes NAME, PARAM_RANGES {key: (lo, hi, type)}, DEFAULTS,
and render(config, writer) -> {"events": [(t, kind)], "result": str, ...}.

Planned (not built yet): quiz.
"""
from engine.formats import color_race, escape_rings, zombie_outbreak

FORMATS = {m.NAME: m for m in (escape_rings, color_race, zombie_outbreak)}
