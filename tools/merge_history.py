"""Merge this run's history.json into the latest one from the repo (used by the daily workflow).

    python tools/merge_history.py MINE.json TARGET.json

Entries are union-ed by (date, format, seed), keeping TARGET's order and appending any new ones from MINE,
so a re-run or an overlapping run never conflicts.
"""
import json
import sys
from pathlib import Path

KEEP = 60


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def key(e):
    return e.get("date"), e.get("format"), e.get("seed")


def main(mine_path, target_path):
    merged = load(target_path)
    seen = {key(e) for e in merged}
    merged += [e for e in load(mine_path) if key(e) not in seen]
    merged.sort(key=lambda e: e.get("date", ""))  # stable: same-day entries keep their order
    Path(target_path).write_text(json.dumps(merged[-KEEP:], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
