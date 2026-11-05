"""Master audio: narration + synthesized SFX + ducked music, placed at exact timeline frames, loudness-normalized."""
import random
import subprocess
import wave
from pathlib import Path

import numpy as np

from .config import MUSIC
from .tts import SR, read_wav

SPEECH_RMS_DB = -20.0  # every clip is brought to the same loudness before mixing


def db(x: float) -> float:
    return 10 ** (x / 20)


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SR)) / SR


def tick() -> np.ndarray:
    t = _t(0.04)
    s = np.sin(2 * np.pi * 1900 * t) * np.exp(-t * 110) + 0.4 * np.sin(2 * np.pi * 3800 * t) * np.exp(-t * 160)
    return s / np.abs(s).max()


def ding() -> np.ndarray:
    t = _t(1.3)
    s = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * d) for f, a, d in [(1318.5, 1.0, 3.2), (1975.5, 0.55, 4.5), (2637.0, 0.3, 6.0), (3951.1, 0.12, 9.0)])
    s *= np.minimum(1, t / 0.004)  # soften the attack click
    return s / np.abs(s).max()


def whoosh(seed: int = 7) -> np.ndarray:
    n = int(0.45 * SR)
    noise = np.random.default_rng(seed).standard_normal(n)
    env = np.sin(np.pi * np.arange(n) / n) ** 2
    cutoff = 0.02 + 0.25 * env  # one-pole low-pass sweeping up then down
    y, out = 0.0, np.empty(n)
    for i in range(n):
        y += cutoff[i] * (noise[i] - y)
        out[i] = y
    out *= env
    return out / np.abs(out).max()


def music_bed(seconds: float, seed: str) -> np.ndarray:
    """Soft ambient pad (royalty-free by construction): slow minor-key chords, gentle tremolo."""
    rng = random.Random(seed)
    progressions = [["A2", "F2", "C3", "G2"], ["D3", "A#2", "F2", "C3"], ["E2", "C3", "G2", "D3"]]
    chord_tones = {"A2": [110.0, 130.81, 164.81], "F2": [87.31, 110.0, 130.81], "C3": [130.81, 164.81, 196.0], "G2": [98.0, 123.47, 146.83],
                   "D3": [146.83, 174.61, 220.0], "A#2": [116.54, 146.83, 174.61], "E2": [82.41, 98.0, 123.47]}
    prog = rng.choice(progressions)
    n = int(seconds * SR)
    out = np.zeros(n)
    chord_len = 4.0
    t_chord = _t(chord_len + 1.5)
    env = np.minimum(1, t_chord / 1.2) * np.minimum(1, (chord_len + 1.5 - t_chord) / 1.5)
    for c, start in enumerate(np.arange(0, seconds, chord_len)):
        tones = chord_tones[prog[c % len(prog)]]
        s = sum(np.sin(2 * np.pi * f * 2 * t_chord + i) + 0.25 * np.sin(2 * np.pi * f * 4 * t_chord) for i, f in enumerate(tones))
        s += 0.6 * np.sin(2 * np.pi * tones[0] * t_chord)  # sub root
        s *= env * (1 + 0.15 * np.sin(2 * np.pi * 0.25 * t_chord))
        a = int(start * SR)
        seg = s[: max(0, min(len(s), n - a))]
        out[a : a + len(seg)] += seg
    return out / (np.abs(out).max() or 1)


def load_music(seconds: float, seed: str) -> np.ndarray:
    """A file from assets/music/ if present (looped), else the synthesized bed."""
    files = sorted(p for p in MUSIC.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg", ".flac"})
    if not files:
        return music_bed(seconds, seed)
    src = random.Random(seed).choice(files)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.3f}", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    return x / (np.abs(x).max() or 1)


def _level(x: np.ndarray) -> np.ndarray:
    rms = np.sqrt(np.mean(x**2)) or 1e-9
    y = x * (db(SPEECH_RMS_DB) / rms)
    peak = np.abs(y).max()
    return y * (db(-1) / peak) if peak > db(-1) else y


def mix(events: list[dict], timeline: dict, clip_dir: Path, cfg: dict, out_wav: Path, seed: str) -> None:
    fps = timeline["fps"]
    spf = SR // fps  # samples per frame: 1600 at 48 kHz / 30 fps, so audio events land exactly on frame boundaries
    total = timeline["totalFrames"] * spf
    m = cfg["mix"]
    speech = np.zeros(total)
    sfx = np.zeros(total)
    sounds = {"tick": tick() * db(m["tick_db"]), "ding": ding() * db(m["ding_db"]), "whoosh": whoosh() * db(m["whoosh_db"])}

    def place(buf: np.ndarray, x: np.ndarray, frame: int) -> None:
        a = frame * spf
        seg = x[: max(0, min(len(x), total - a))]
        buf[a : a + len(seg)] += seg

    speaking = np.zeros(timeline["totalFrames"], dtype=bool)
    for e in events:
        if e["kind"] == "speech":
            place(speech, _level(read_wav(clip_dir / f"{e['key']}.wav").astype(np.float64)), e["frame"])
            speaking[e["frame"] : e["frame"] + e["frames"]] = True
        else:
            place(sfx, sounds[e["kind"]], e["frame"])

    # Duck music under speech: per-frame gain, widened 4 frames each side, smoothed over 6 frames.
    duck = np.convolve(speaking.astype(float), np.ones(9), "same") > 0
    duck = np.convolve(duck.astype(float), np.ones(6) / 6, "same")
    music_gain = db(m["music_db"]) * 10 ** (m["music_duck_db"] * duck / 20)
    music = load_music(total / SR, seed) * np.repeat(music_gain, spf)

    master = speech + sfx + music[:total]
    _write(out_wav.with_name("speech_stem.wav"), speech)  # narration only, for the validator's silencedetect
    raw = out_wav.with_suffix(".raw.wav")
    _write(raw, master, channels=2)
    loudnorm(raw, out_wav, m["target_lufs"])


def _write(path: Path, x: np.ndarray, channels: int = 1) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    if channels == 2:
        pcm = np.repeat(pcm, 2)  # dual mono, so Remotion's stereo AAC keeps the measured loudness
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def lufs(path: Path) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    return float(err.rsplit("I:", 1)[1].split("LUFS")[0])


def loudnorm(src: Path, dst: Path, target: float) -> None:
    """Gain to `target` LUFS + true-peak limiter at -1.5 dBFS. The limiter shaves a little loudness, so re-measure and correct."""
    gain = target - lufs(src)
    for _ in range(3):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", f"volume={gain:.2f}dB,alimiter=limit=0.84:attack=3:release=50:level=false",
                        "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(dst)], check=True)
        miss = target - lufs(dst)
        if abs(miss) <= 0.3:
            return
        gain += miss
