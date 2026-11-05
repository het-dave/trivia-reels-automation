"""Pre-publish gate. Any returned error means the reel is NOT published."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .audio import lufs

AN_SR = 16000  # analysis sample rate


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def decode_audio(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(AN_SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def silence_seconds(path: Path, noise_db: int, min_dur: float) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    return sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", err))


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-9) if len(x) else -120.0


def check_media(mp4: Path, timeline: dict, max_seconds: float, target_lufs: float) -> list[str]:
    errors = []
    info = probe(mp4)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    expected = timeline["totalFrames"] / timeline["fps"]
    if not v:
        return ["no video stream"]
    if (v["width"], v["height"]) != (1080, 1920):
        errors.append(f"resolution {v['width']}x{v['height']} != 1080x1920")
    if v["codec_name"] != "h264" or v.get("pix_fmt") != "yuv420p":
        errors.append(f"video codec {v['codec_name']}/{v.get('pix_fmt')} != h264/yuv420p")
    if v["r_frame_rate"] != "30/1":
        errors.append(f"frame rate {v['r_frame_rate']} != 30/1")
    dur = float(info["format"]["duration"])
    if abs(dur - expected) > 0.2:
        errors.append(f"duration {dur:.2f}s != timeline {expected:.2f}s")
    if not 3 <= dur <= max_seconds + 0.5:
        errors.append(f"duration {dur:.2f}s outside 3..{max_seconds}s")
    if not a:
        return errors + ["no audio track (voiceover missing)"]
    if a["codec_name"] != "aac" or int(a["sample_rate"]) > 48000 or a["channels"] not in (1, 2):
        errors.append(f"audio {a['codec_name']} {a['sample_rate']}Hz {a['channels']}ch not AAC <=48kHz mono/stereo")
    a_dur = float(a.get("duration") or 0)
    if abs(a_dur - float(v.get("duration") or dur)) > 0.15:
        errors.append(f"audio length {a_dur:.2f}s != video length {v.get('duration')}s")
    if any(float(st.get("start_time") or 0) != 0 for st in (v, a)):
        errors.append(f"streams don't start at 0 (video {v.get('start_time')}, audio {a.get('start_time')})")
    head = mp4.read_bytes()
    head = head[: head.find(b"mdat")]
    if b"moov" not in head or b"elst" in head:
        errors.append("moov atom not before mdat, or edit list present (Instagram rejects both)")
    loud = lufs(mp4)
    if abs(loud - target_lufs) > 1.0:
        errors.append(f"loudness {loud:.1f} LUFS, expected {target_lufs} +/- 1")
    return errors


def check_voice(mp4: Path, stem: Path, timeline: dict, events: list[dict]) -> list[str]:
    """Narration really is in the final file, at the timeline's speech windows, and isn't mostly silence."""
    errors = []
    fps = timeline["fps"]
    x = decode_audio(mp4)
    win = lambda f0, n: x[int(f0 / fps * AN_SR) : int((f0 + n) / fps * AN_SR)]
    speech = [e for e in events if e["kind"] == "speech"]
    speech_db = [rms_db(win(e["frame"], e["frames"])) for e in speech]
    # Countdown windows hold only ticks + music: speech windows must be clearly louder.
    timers = [(q["from"] + q["timerAt"], timeline["timerFrames"]) for q in timeline["questions"]]
    timer_db = [rms_db(win(f, n)) for f, n in timers]
    quiet = [e["key"] for e, d in zip(speech, speech_db) if d < -35]
    if quiet:
        errors.append(f"narration missing/too quiet in final audio for: {', '.join(quiet[:5])}")
    if timer_db and np.median(speech_db) - np.median(timer_db) < 6:
        errors.append(f"speech not distinguishable from countdown windows ({np.median(speech_db):.1f} vs {np.median(timer_db):.1f} dB)")
    # silencedetect on the narration stem: real speech for a large share of the reel.
    total = timeline["totalFrames"] / fps
    voiced = total - silence_seconds(stem, -40, 0.35)
    if voiced / total < 0.4:
        errors.append(f"voiceover is mostly silence ({voiced:.1f}s of {total:.1f}s voiced)")
    # A/V sync: every countdown tick must start within 20 ms of its frame.
    hp = np.convolve(np.abs(np.diff(x, prepend=0)), np.ones(16) / 16, "same")
    worst = 0.0
    for e in (e for e in events if e["kind"] == "tick"):
        t = e["frame"] / fps
        a, b = int((t - 0.12) * AN_SR), int((t + 0.12) * AN_SR)
        seg = hp[max(a, 0) : b]
        if len(seg) and seg.max() > 0:
            worst = max(worst, abs((max(a, 0) + int(np.argmax(seg > seg.max() * 0.5))) / AN_SR - t))
    if worst > 0.02:
        errors.append(f"audio out of sync: tick off by {worst * 1000:.0f} ms")
    # Whole-file silencedetect: no dropout anywhere.
    if silence_seconds(mp4, -50, 1.5) > 0:
        errors.append("final audio contains a silent gap >= 1.5s")
    return errors


def check_post(n_questions: int, n_min: int, caption: str) -> list[str]:
    errors = []
    if n_questions < n_min:
        errors.append(f"only {n_questions} questions (min {n_min})")
    if not caption.strip():
        errors.append("empty caption")
    if len(caption) > 2200:
        errors.append(f"caption {len(caption)} chars > 2200")
    if caption.count("#") > 30:
        errors.append("more than 30 hashtags")
    return errors


def validate(mp4: Path, stem: Path, timeline: dict, events: list[dict], n_questions: int, caption: str, cfg: dict) -> list[str]:
    errors = check_post(n_questions, cfg["questions"]["min"], caption) + check_media(mp4, timeline, cfg["max_duration_seconds"], cfg["mix"]["target_lufs"])
    if not any("audio track" in e for e in errors):
        errors += check_voice(mp4, stem, timeline, events)
    return errors
