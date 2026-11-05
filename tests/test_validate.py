"""Builds real (tiny) MP4s with ffmpeg and runs them through the publish gate."""
import subprocess
import wave

import numpy as np
import pytest

from trivia import audio, timeline, validate
from trivia.tts import SR

D = {"hook1": 1.0, "q0": 1.5, "r0": 1.5, "outro": 1.0, **{f"q0o{k}": 0.5 for k in range(4)}}


def speechy(seconds):
    t = np.arange(int(seconds * SR)) / SR
    return 0.3 * (np.sin(2 * np.pi * 180 * t) + 0.5 * np.sin(2 * np.pi * 720 * t)) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))


def write_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


@pytest.fixture(scope="module")
def reel(tmp_path_factory):
    from trivia import config

    cfg = config.load()
    d = tmp_path_factory.mktemp("reel")
    clips = d / "clips"
    clips.mkdir()
    for k, s in D.items():
        write_wav(clips / f"{k}.wav", speechy(s))
    tl, ev = timeline.build(D, 1, 3)
    audio.mix(ev, tl, clips, cfg, d / "master.wav", "test")
    return cfg, d, tl, ev


def encode(out, audio_args, size="1080x1920", seconds=None):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=purple:s={size}:r=30:d={seconds}", *audio_args,
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-shortest", str(out.with_suffix(".tmp.mp4"))], check=True)
    # same post-processing as trivia/render.py
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(out.with_suffix(".tmp.mp4")), "-c", "copy", "-bsf:a", "noise=drop=lt(pts\\,0)",
                    "-movflags", "+faststart+negative_cts_offsets", "-use_editlist", "0", str(out)], check=True)


def test_good_reel_passes(reel):
    cfg, d, tl, ev = reel
    secs = tl["totalFrames"] / 30
    encode(d / "good.mp4", ["-i", str(d / "master.wav")], seconds=secs)
    assert validate.validate(d / "good.mp4", d / "speech_stem.wav", tl, ev, 8, "caption #trivia", cfg) == []


def test_master_is_loudness_normalized(reel):
    _, d, _, _ = reel
    assert abs(audio.lufs(d / "master.wav") - (-14)) <= 0.5
    peak = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(d / "master.wav"), "-af", "astats", "-f", "null", "-"], capture_output=True, text=True).stderr
    assert float(peak.rsplit("Peak level dB:", 1)[1].split()[0]) <= -1.0


def test_silent_reel_fails(reel):
    cfg, d, tl, ev = reel
    secs = tl["totalFrames"] / 30
    encode(d / "silent.mp4", ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={secs}"], seconds=secs)
    write_wav(d / "silent_stem.wav", np.zeros(int(secs * SR)))
    errors = validate.validate(d / "silent.mp4", d / "silent_stem.wav", tl, ev, 8, "caption", cfg)
    assert any("narration missing" in e for e in errors)
    assert any("mostly silence" in e for e in errors)


def test_missing_audio_wrong_size_and_short_reel_fail(reel):
    cfg, d, tl, ev = reel
    secs = tl["totalFrames"] / 30
    encode(d / "mute.mp4", ["-an"], size="720x1280", seconds=secs)
    errors = validate.validate(d / "mute.mp4", d / "speech_stem.wav", tl, ev, 7, "", cfg)
    joined = " | ".join(errors)
    assert "no audio track" in joined and "resolution" in joined and "only 7 questions" in joined and "empty caption" in joined


def test_audio_delay_fails(reel):
    cfg, d, tl, ev = reel
    encode(d / "late.mp4", ["-itsoffset", "0.08", "-i", str(d / "master.wav")], seconds=tl["totalFrames"] / 30)
    errors = validate.validate(d / "late.mp4", d / "speech_stem.wav", tl, ev, 8, "c", cfg)
    assert any("out of sync" in e for e in errors)


def test_duration_mismatch_fails(reel):
    cfg, d, tl, ev = reel
    encode(d / "short.mp4", ["-i", str(d / "master.wav")], seconds=tl["totalFrames"] / 30 - 2)
    errors = validate.validate(d / "short.mp4", d / "speech_stem.wav", tl, ev, 8, "c", cfg)
    assert any("duration" in e for e in errors)
