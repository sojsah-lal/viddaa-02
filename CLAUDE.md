# TikTok Autopilot

Daily pipeline: `run.py` = plan → validate → render → QA → publish → append `history.json`.

## Rules (do not violate)
- AI only decides: the LLM outputs a small config JSON; it never writes code. All rendering is deterministic code.
- Never fail silently, never skip a day: bad/missing LLM output → preset; missing TikTok secrets → skip upload, keep MP4.
- `python run.py` with zero env vars must produce a valid MP4.
- Audio is synthesized from public-domain melodies in `engine/melodies.py` only.
- Same config + seed = identical video. Use the seeded RNGs, never unseeded randomness, inside formats.

## Layout
- `engine/formats/<name>.py`: each exposes `NAME`, `PARAM_RANGES {key: (lo, hi, type)}`, `DEFAULTS`,
  `render(config, writer) -> {"events", "result"}`. The module docstring is sent to the LLM as the format description.
  Register new formats in `engine/formats/__init__.py` and add ≥3 presets as `presets/<format>_N.json`.
- `planner/validate.py` is the only gate between LLM output and the engine.
- Video: 1080x1920, 30 fps, H.264 + AAC. Hook text stays in y 180–420; keep the bottom 350 px clear.

## Dev
- Windows: use `.venv\Scripts\python.exe` (Python 3.12). FFmpeg is found via PATH or the WinGet package folder.
- Quick checks: `python run.py --no-publish`, `python -m qa.check <mp4>`.
