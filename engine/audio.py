"""Procedural audio: event-timed notes from a melody, mixed to a 16-bit WAV."""
import random
import wave
from pathlib import Path

import numpy as np

SR = 44100
NOTE_THROTTLE = 0.06


def midi_to_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def tone(midi: float, length=0.6, decay=0.35, bright=1.0) -> np.ndarray:
    """Sine + 2 harmonics, fast attack, exponential decay."""
    t = np.arange(int(length * SR)) / SR
    f = midi_to_hz(midi)
    w = (np.sin(2 * np.pi * f * t)
         + 0.45 * bright * np.sin(2 * np.pi * 2 * f * t)
         + 0.2 * bright * np.sin(2 * np.pi * 3 * f * t))
    env = (1 - np.exp(-t / 0.004)) * np.exp(-t * 5.0 / decay)
    return (w * env).astype(np.float32)


def pop(rng: np.random.Generator, length=0.06) -> np.ndarray:
    n = int(length * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    noise = np.diff(noise, prepend=0)  # crude high-pass
    return noise * np.exp(-np.arange(n) / SR / 0.012).astype(np.float32)


def _mix(buf: np.ndarray, s: np.ndarray, t: float, gain: float):
    i = int(t * SR)
    if i >= len(buf):
        return
    end = min(len(buf), i + len(s))
    buf[i:end] += gain * s[:end - i]


def build_track(events, duration: float, melody: list, seed: int = 0) -> np.ndarray:
    """events: [(time_s, kind)] with kind in bounce|break|win|end."""
    buf = np.zeros(int(duration * SR) + 1, dtype=np.float32)
    rnd = random.Random(seed)
    nrng = np.random.default_rng(seed)
    idx, last = 0, -1.0
    for t, kind in sorted(events, key=lambda e: e[0]):
        root = melody[idx % len(melody)]
        if kind == "bounce":
            if t - last < NOTE_THROTTLE:
                continue
            last = t
            _mix(buf, tone(root), t, 0.5 * rnd.uniform(0.82, 1.0))
            idx += 1
        elif kind == "break":
            for k, iv in enumerate((0, 4, 7)):
                _mix(buf, tone(root + 12 + iv, 0.8, 0.5, bright=1.6), t + 0.012 * k, 0.32)
            _mix(buf, pop(nrng), t, 0.5)
            idx += 1
        elif kind == "win":
            base = melody[0]
            for k, iv in enumerate((0, 4, 7, 12, 16)):
                _mix(buf, tone(base + 12 + iv, 1.4, 1.2, bright=1.3), t + 0.09 * k, 0.35)
        elif kind == "end":
            base = melody[0]
            for k, iv in enumerate((7, 3, 0, -5)):
                _mix(buf, tone(base + iv, 1.0, 0.9), t + 0.16 * k, 0.4)
    return master(buf)


def master(buf: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(buf))) or 1.0
    buf = buf / max(1.0, peak / 1.5)
    buf = np.tanh(buf)  # soft limit
    peak = float(np.max(np.abs(buf))) or 1.0
    return buf * (10 ** (-1 / 20) / peak)


def write_wav(path: Path, samples: np.ndarray):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())
