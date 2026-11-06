"""Render the QuizReel Remotion composition from Python-built props + master audio."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import REMOTION


def render(props: dict, master_wav: Path, out_mp4: Path, cfg: dict, log=print) -> float:
    run_dir = REMOTION / "public" / "run"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    shutil.copy(master_wav, run_dir / "master.wav")
    props = {**props, "audio": "run/master.wav"}
    props_file = run_dir / "props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False))
    r = cfg["render"]
    raw = out_mp4.with_suffix(".remotion.mp4")
    cmd = ["npx", "remotion", "render", "src/index.ts", "QuizReel", str(raw.resolve()),
           f"--props={props_file.resolve()}", "--codec=h264", f"--crf={r['crf']}", f"--x264-preset={r['x264_preset']}",
           "--pixel-format=yuv420p", "--audio-codec=aac", "--audio-bitrate=128k", "--sample-rate=48000",
           "--enforce-audio-track", f"--concurrency={r['concurrency'] or os.cpu_count()}", "--overwrite", "--log=info"]
    t0 = time.time()
    subprocess.run(cmd, cwd=REMOTION, check=True)
    secs = time.time() - t0
    instagram_remux(raw, out_mp4)
    raw.unlink()
    log(f"  remotion render: {secs:.0f}s")
    return secs


def instagram_remux(src: Path, dst: Path, negative_cts: bool = True) -> None:
    """Instagram wants the moov atom up front and no edit lists. Without an edit list, players would play the AAC
    priming packets (negative pts, ~43 ms) and delay the B-frame video by 2 frames, so drop the priming packets
    and use negative CTS offsets: audio and video both start at exactly 0 (checked by validate.check_media/check_voice)."""
    flags = "+faststart+negative_cts_offsets" if negative_cts else "+faststart"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c", "copy", "-bsf:a", "noise=drop=lt(pts\\,0)",
                    "-movflags", flags, "-use_editlist", "0", str(dst)], check=True)
