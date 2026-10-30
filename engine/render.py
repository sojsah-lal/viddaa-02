"""config.json -> frames -> FFmpeg -> MP4 (+ audio mux)."""
import argparse
import json
import subprocess
from pathlib import Path

from engine import audio, common as C
from engine.formats import FORMATS
from engine.melodies import MELODIES


def render(config: dict, out_path: Path) -> dict:
    module = FORMATS[config["format"]]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_video = out_path.with_name(out_path.stem + ".video.mp4")
    tmp_wav = out_path.with_name(out_path.stem + ".wav")

    C.init()
    with C.FrameWriter(tmp_video) as writer:
        result = module.render(config, writer)
    duration = writer.seconds

    melody = MELODIES.get(config.get("melody"), MELODIES["ode_to_joy"])
    audio.write_wav(tmp_wav, audio.build_track(result["events"], duration, melody, config.get("seed", 0)))

    subprocess.run([C.ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(tmp_video), "-i", str(tmp_wav),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "44100", "-shortest", "-movflags", "+faststart", str(out_path)], check=True)
    tmp_video.unlink(missing_ok=True)
    tmp_wav.unlink(missing_ok=True)

    result["duration"] = round(duration, 2)
    result.pop("events", None)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render one config to MP4")
    ap.add_argument("config")
    ap.add_argument("out")
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    print(json.dumps(render(cfg, Path(a.out)), indent=2))
