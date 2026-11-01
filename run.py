"""Orchestrator: plan -> validate -> render -> qa -> publish -> append history.json."""
import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")  # hooks contain emoji; Windows consoles default to cp1252

from engine.render import render  # noqa: E402
from planner.plan import plan  # noqa: E402
from planner.validate import fallback, validate  # noqa: E402
from publish.tiktok_upload import PublishError, summary, upload  # noqa: E402
from qa.check import check  # noqa: E402

HISTORY = ROOT / "history.json"
OUTPUT = ROOT / "output"
BANGKOK = timezone(timedelta(hours=7))
KEEP_HISTORY = 60


def load_history() -> list:
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def caption_text(cfg: dict) -> str:
    caption = cfg.get("caption", "").strip()
    tags = [f"#{t}" for t in cfg.get("hashtags", []) if f"#{t}".lower() not in caption.lower()]
    return " ".join([caption, *tags]).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="use this config.json and skip planning")
    ap.add_argument("--no-publish", action="store_true", help="render and QA only")
    ap.add_argument("--format", help="force a format")
    ap.add_argument("--seed", type=int, help="force the render seed")
    args = ap.parse_args()

    now = datetime.now(BANGKOK)
    day = now.strftime("%Y-%m-%d")
    history = load_history()
    last_format = history[-1]["format"] if history else None
    rng = random.Random()

    if args.config:
        raw, source = json.loads(Path(args.config).read_text(encoding="utf-8")), "file"
    else:
        raw, source = plan(history[-14:], rng, args.format)
    cfg, problem = validate(raw, rng, last_format=last_format, only_format=args.format)
    if problem:
        source = f"{source}->fallback ({problem})"
    if args.seed is not None:
        cfg["seed"] = args.seed
    print(f"[run] {day} format={cfg['format']} source={source}\n[run] hook: {cfg['hook']}")

    OUTPUT.mkdir(exist_ok=True)
    video = OUTPUT / f"{day}_{cfg['format']}.mp4"
    result = render(cfg, video)
    issues = check(video)
    if issues:
        print(f"[qa] failed: {issues}; retrying once with a fallback preset")
        cfg = fallback(rng, avoid_format=cfg["format"], only_format=args.format)
        source += " -> qa-retry"
        video.unlink(missing_ok=True)
        video = OUTPUT / f"{day}_{cfg['format']}.mp4"
        result = render(cfg, video)
        issues = check(video)
    if issues:
        for p in issues:
            print(f"QA FAIL: {p}")
        summary("## ❌ QA failed\n" + "\n".join(f"- {p}" for p in issues))
        sys.exit(1)
    print(f"[qa] OK — {video.name} ({result['duration']}s, {result['result']})")
    if "deadline" in result:  # escape_rings picks its deadline while rendering
        cfg["hook"] = cfg["hook"].replace("{X}", str(result["deadline"])).replace("{x}", str(result["deadline"]))

    caption = caption_text(cfg)
    (OUTPUT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT / "caption.txt").write_text(caption + "\n", encoding="utf-8")

    status, exit_code = "not-requested", 0
    if not args.no_publish:
        try:
            status = upload(video)
        except (PublishError, OSError, ValueError) as e:
            status, exit_code = f"failed: {e}", 1
            print(f"[publish] {status}")

    summary(f"## 🎬 {day} — {cfg['format']}\n"
            f"- Hook: **{cfg['hook']}**\n- Result: {result['result']} ({result['duration']}s)\n"
            f"- Planner: {source}\n- TikTok: `{status}`\n\n"
            "### Caption (copy into TikTok, and switch on the AI-generated label)\n"
            f"```\n{caption}\n```\n")

    history.append({"date": day, "format": cfg["format"], "hook": cfg["hook"], "palette": cfg["palette"],
                    "melody": cfg["melody"], "seed": cfg["seed"], "source": source.split(" ")[0],
                    "result": result["result"], "publish": status,
                    **({"players": [p["name"] for p in cfg["players"]]} if cfg.get("players") else {})})
    HISTORY.write_text(json.dumps(history[-KEEP_HISTORY:], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[run] publish={status}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
