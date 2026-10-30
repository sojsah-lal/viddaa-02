"""ffprobe-based QA. `python -m qa.check video.mp4` exits non-zero on any problem."""
import json
import re
import subprocess
import sys
from pathlib import Path

from engine.common import H, W, ffmpeg_bin

MIN_S, MAX_S = 12, 50
MIN_BYTES = 300 * 1024


def check(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return [f"{path} does not exist"]
    problems = []
    probe = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-print_format", "json",
                            "-show_format", "-show_streams", str(path)],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        return [f"ffprobe could not read the file: {probe.stderr.strip()[:200]}"]
    info = json.loads(probe.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration", 0))
    if not MIN_S <= duration <= MAX_S:
        problems.append(f"duration {duration:.1f}s outside {MIN_S}-{MAX_S}s")
    if audio is None:
        problems.append("no audio stream")
    if video is None:
        problems.append("no video stream")
    elif (video.get("width"), video.get("height")) != (W, H):
        problems.append(f"resolution {video.get('width')}x{video.get('height')} != {W}x{H}")
    size = path.stat().st_size
    if size < MIN_BYTES:
        problems.append(f"file only {size} bytes")
    black = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=1:pix_th=0.10",
                            "-an", "-f", "null", "-"], capture_output=True, text=True)
    spans = re.findall(r"black_start:(\S+) black_end:(\S+) black_duration:(\S+)", black.stderr)
    for start, end, dur in spans:
        problems.append(f"black frames {start}s-{end}s ({dur}s)")
    return problems


if __name__ == "__main__":
    issues = check(Path(sys.argv[1]))
    for p in issues:
        print(f"QA FAIL: {p}")
    print("QA OK" if not issues else f"{len(issues)} problem(s)")
    sys.exit(1 if issues else 0)
