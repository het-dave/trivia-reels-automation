"""Narration-driven frame timeline. Pure: takes measured clip durations, returns exact frames.

Clip keys: hook{n}, q{i}, q{i}o{k} (k=0..3), r{i}, outro.
Every speech clip gets its own window; the countdown window contains only ticks.
"""
import math

FPS = 30
HOOK_VOICE_AT = 0.25
MIN_SCENE = 2.0
Q_VOICE_AT = 0.35  # after the whoosh
OPTION_GAP = 0.2
TIMER_GAP = 0.35  # after the last option is spoken
REVEAL_VOICE_AT = 0.3  # after the ding
SCENE_TAIL = 0.6
OUTRO_TAIL = 0.9


def build(durs: dict[str, float], n: int, timer_s: int, fps: int = FPS) -> tuple[dict, list[dict]]:
    sec = lambda s: int(round(s * fps))
    clip = lambda key: math.ceil(durs[key] * fps)
    events: list[dict] = []

    def speech(key: str, frame: int) -> int:
        events.append({"kind": "speech", "key": key, "frame": frame, "frames": clip(key)})
        return frame + clip(key)

    hook_key = f"hook{n}"
    end = speech(hook_key, sec(HOOK_VOICE_AT)) + sec(0.45)
    hook = {"from": 0, "dur": max(end, sec(MIN_SCENE))}
    t = hook["dur"]

    questions = []
    timer_frames = timer_s * fps
    for i in range(n):
        start = t
        events.append({"kind": "whoosh", "frame": start})
        cur = speech(f"q{i}", start + sec(Q_VOICE_AT))
        options_at = []
        for k in range(4):
            cur += sec(OPTION_GAP)
            options_at.append(cur - start)
            cur = speech(f"q{i}o{k}", cur)
        timer = cur + sec(TIMER_GAP)
        for s in range(timer_s):
            events.append({"kind": "tick", "frame": timer + s * fps})
        reveal = timer + timer_frames
        events.append({"kind": "ding", "frame": reveal})
        end = speech(f"r{i}", reveal + sec(REVEAL_VOICE_AT)) + sec(SCENE_TAIL)
        questions.append(
            {"from": start, "dur": end - start, "optionsAt": options_at, "timerAt": timer - start, "revealAt": reveal - start}
        )
        t = end

    events.append({"kind": "whoosh", "frame": t})
    out_end = speech("outro", t + sec(0.3)) + sec(OUTRO_TAIL)
    outro = {"from": t, "dur": max(out_end - t, sec(MIN_SCENE))}
    timeline = {
        "fps": fps,
        "totalFrames": t + outro["dur"],
        "timerFrames": timer_frames,
        "hook": hook,
        "outro": outro,
        "questions": questions,
    }
    return timeline, events


def fit(durs: dict[str, float], available: int, n_min: int, max_seconds: float, timer_s: int, fps: int = FPS) -> int:
    """Largest question count (<= available, >= n_min) whose reel fits max_seconds. Never speeds up the voice."""
    for n in range(available, n_min - 1, -1):
        tl, _ = build(durs, n, timer_s, fps)
        if tl["totalFrames"] <= max_seconds * fps:
            return n
    raise ValueError(f"even {n_min} questions exceed {max_seconds}s of narration")
