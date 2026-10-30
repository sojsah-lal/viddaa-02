"""Procedural audio: event-timed notes from a melody, mixed to a 16-bit stereo WAV.

Events are (time_s, kind) or (time_s, kind, pan) with pan in -1 (left) .. 1 (right).
"""
import random
import wave
from pathlib import Path

import numpy as np

SR = 44100
NOTE_THROTTLE = 0.06
RISER_SECONDS = 2.2


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


def pad(root: int, duration: float) -> np.ndarray:
    """Quiet sustained root + fifth with a slow swell, under everything."""
    t = np.arange(int(duration * SR)) / SR
    w = np.zeros_like(t)
    for m, g in ((root, 1.0), (root + 7, 0.6), (root + 12, 0.35)):
        f = midi_to_hz(m)
        w += g * np.sin(2 * np.pi * f * t + 0.3 * np.sin(2 * np.pi * 0.2 * t))
    swell = 0.75 + 0.25 * np.sin(2 * np.pi * t / 6.0)
    fade = np.clip(t / 1.5, 0, 1) * np.clip((duration - t) / 1.0, 0, 1)
    return (w * swell * fade).astype(np.float32)


def riser(length=RISER_SECONDS) -> np.ndarray:
    """Upward sine sweep that swells into the finish."""
    t = np.arange(int(length * SR)) / SR
    f = 220 * (6 ** (t / length))
    phase = 2 * np.pi * np.cumsum(f) / SR
    env = (t / length) ** 2
    return (np.sin(phase) * env + 0.5 * np.sin(2 * phase) * env).astype(np.float32)


def _mix(buf: np.ndarray, s: np.ndarray, t: float, gain: float, pan: float = 0.0):
    i = int(t * SR)
    if i >= len(buf) or i + len(s) <= 0:
        return
    if i < 0:
        s, i = s[-i:], 0
    end = min(len(buf), i + len(s))
    a = (pan + 1) * np.pi / 4  # equal-power pan
    buf[i:end, 0] += gain * np.cos(a) * s[:end - i]
    buf[i:end, 1] += gain * np.sin(a) * s[:end - i]


def build_track(events, duration: float, melody: list, seed: int = 0) -> np.ndarray:
    """events: [(t, kind[, pan])] with kind in bounce|break|win|end. Returns (n, 2) float32."""
    buf = np.zeros((int(duration * SR) + 1, 2), dtype=np.float32)
    rnd = random.Random(seed)
    nrng = np.random.default_rng(seed)
    idx, last = 0, -1.0
    _mix(buf, pad(min(melody) - 12, duration), 0, 0.07)
    for ev in sorted(events, key=lambda e: e[0]):
        t, kind = ev[0], ev[1]
        p = max(-1.0, min(1.0, ev[2] if len(ev) > 2 else 0.0)) * 0.7
        root = melody[idx % len(melody)]
        if kind == "bounce":
            if t - last < NOTE_THROTTLE:
                continue
            last = t
            _mix(buf, tone(root), t, 0.5 * rnd.uniform(0.82, 1.0), p)
            idx += 1
        elif kind == "break":
            for k, iv in enumerate((0, 4, 7)):
                _mix(buf, tone(root + 12 + iv, 0.8, 0.5, bright=1.6), t + 0.012 * k, 0.32, p)
            _mix(buf, pop(nrng), t, 0.5, p)
            idx += 1
        elif kind in ("win", "end"):
            _mix(buf, riser(), t - RISER_SECONDS, 0.10)
            base = melody[0]
            if kind == "win":
                for k, iv in enumerate((0, 4, 7, 12, 16)):
                    _mix(buf, tone(base + 12 + iv, 1.4, 1.2, bright=1.3), t + 0.09 * k, 0.35, (k - 2) * 0.3)
                _mix(buf, pop(nrng, 0.12), t, 0.6)
            else:
                for k, iv in enumerate((7, 3, 0, -5)):
                    _mix(buf, tone(base + iv, 1.0, 0.9), t + 0.16 * k, 0.4)
    return master(echo(buf))


def echo(buf: np.ndarray) -> np.ndarray:
    """Two ping-pong taps for a sense of space."""
    out = buf.copy()
    for delay, gain, swap in ((0.19, 0.26, True), (0.38, 0.12, False)):
        d = int(delay * SR)
        src = buf[:-d, ::-1] if swap else buf[:-d]
        out[d:] += gain * src
    return out


def master(buf: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(buf))) or 1.0
    buf = buf / max(1.0, peak / 1.5)
    buf = np.tanh(buf)  # soft limit
    peak = float(np.max(np.abs(buf))) or 1.0
    return buf * (10 ** (-1 / 20) / peak)


def write_wav(path: Path, samples: np.ndarray):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    if pcm.ndim == 1:
        pcm = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
