"""Voiceover: edge-tts (primary) -> Piper (offline fallback). Never returns without real speech for every line."""
import asyncio
import os
import random
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000
# Trim leading/trailing silence so measured durations are the real speech length.
TRIM = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.04,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.04,areverse")


class TTSFailed(RuntimeError):
    pass


def to_wav(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", TRIM, "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)], check=True)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def check_clip(path: Path) -> float:
    """Duration in seconds; raises if the clip is empty or silent."""
    x = read_wav(path)
    dur = len(x) / SR
    if dur < 0.25 or np.abs(x).max() < 0.03:
        raise TTSFailed(f"{path.name}: silent or empty clip ({dur:.2f}s)")
    return dur


async def _edge_all(lines: dict[str, str], outdir: Path, voice: str, attempts: int) -> None:
    import edge_tts

    sem = asyncio.Semaphore(4)

    async def one(key: str, text: str) -> None:
        mp3 = outdir / f"{key}.mp3"
        last = None
        for i in range(attempts):
            try:
                async with sem:
                    await edge_tts.Communicate(text, voice).save(str(mp3))
                if mp3.stat().st_size > 1000:
                    return
                last = "empty audio"
            except Exception as e:  # network / 403 / websocket errors from the unofficial service
                last = f"{type(e).__name__}: {e}"
            await asyncio.sleep(2 ** i + random.random())
        raise TTSFailed(f"edge-tts failed for {key} after {attempts} attempts: {last}")

    await asyncio.gather(*(one(k, t) for k, t in lines.items()))
    for k in lines:
        to_wav(outdir / f"{k}.mp3", outdir / f"{k}.wav")


def piper_model(name: str) -> Path:
    d = Path(os.environ.get("PIPER_VOICE_DIR", Path.home() / ".cache" / "piper"))
    model = d / f"{name}.onnx"
    if not model.exists():
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "piper.download_voices", name, "--data-dir", str(d)], check=True)
    return model


def _piper_all(lines: dict[str, str], outdir: Path, name: str) -> None:
    from piper import PiperVoice

    voice = PiperVoice.load(str(piper_model(name)))
    for k, text in lines.items():
        raw = outdir / f"{k}.piper.wav"
        with wave.open(str(raw), "wb") as w:
            voice.synthesize_wav(text, w)
        to_wav(raw, outdir / f"{k}.wav")


def synthesize(lines: dict[str, str], outdir: Path, cfg: dict, force_piper: bool = False, log=print) -> tuple[str, dict[str, float]]:
    """Synthesize every line with ONE engine (no mixed voices in a reel). Returns (engine, {key: seconds})."""
    outdir.mkdir(parents=True, exist_ok=True)
    v = cfg["voice"]
    errors = []
    if not force_piper:
        try:
            asyncio.run(_edge_all(lines, outdir, v["edge"], v["edge_attempts"]))
            return "edge-tts", {k: check_clip(outdir / f"{k}.wav") for k in lines}
        except Exception as e:
            errors.append(f"edge-tts: {e}")
            log(f"  edge-tts failed, switching to Piper: {e}")
    try:
        _piper_all(lines, outdir, v["piper"])
        return "piper", {k: check_clip(outdir / f"{k}.wav") for k in lines}
    except Exception as e:
        errors.append(f"piper: {e}")
    raise TTSFailed("both TTS engines failed -> " + " | ".join(errors))
