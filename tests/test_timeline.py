import pytest

from trivia import timeline


def durs(n, q=6.0, opt=0.8, r=6.5, hook=3.0, outro=2.8):
    d = {f"hook{k}": hook for k in range(1, n + 1)}
    d["outro"] = outro
    for i in range(n):
        d[f"q{i}"], d[f"r{i}"] = q, r
        for k in range(4):
            d[f"q{i}o{k}"] = opt
    return d


def speech_windows(events):
    return [(e["frame"], e["frame"] + e["frames"], e["key"]) for e in events if e["kind"] == "speech"]


def test_timer_is_exact_and_speech_free():
    tl, ev = timeline.build(durs(8), 8, timer_s=3)
    assert tl["timerFrames"] == 90
    for q in tl["questions"]:
        assert q["revealAt"] - q["timerAt"] == 90
        t0, t1 = q["from"] + q["timerAt"], q["from"] + q["revealAt"]
        for a, b, key in speech_windows(ev):
            assert b <= t0 or a >= t1, f"{key} overlaps countdown"
    ticks = [e["frame"] for e in ev if e["kind"] == "tick"]
    assert len(ticks) == 8 * 3


def test_speech_never_overlaps_or_gets_cut():
    tl, ev = timeline.build(durs(10), 10, timer_s=3)
    w = sorted(speech_windows(ev))
    assert all(w[i][1] <= w[i + 1][0] for i in range(len(w) - 1))
    for i, q in enumerate(tl["questions"]):
        end = q["from"] + q["dur"]
        for a, b, key in w:
            if key.startswith((f"q{i}", f"r{i}")) and not key.startswith(f"q{i}0"):
                assert q["from"] <= a and b <= end, f"{key} spills out of its scene"
    assert w[-1][1] <= tl["totalFrames"]


def test_clip_lengths_rounded_up_to_frames():
    d = durs(1, q=1.001)
    _, ev = timeline.build(d, 1, timer_s=3)
    q0 = next(e for e in ev if e.get("key") == "q0")
    assert q0["frames"] == 31  # ceil(1.001 * 30): never truncate speech


def test_options_appear_in_order_during_their_narration():
    tl, ev = timeline.build(durs(2), 2, timer_s=3)
    q = tl["questions"][1]
    starts = {e["key"]: e["frame"] for e in ev if e["kind"] == "speech"}
    assert q["optionsAt"] == sorted(q["optionsAt"])
    assert [q["from"] + a for a in q["optionsAt"]] == [starts[f"q1o{k}"] for k in range(4)]


def test_scenes_are_contiguous_and_total_matches():
    tl, _ = timeline.build(durs(9), 9, timer_s=3)
    t = tl["hook"]["dur"]
    for q in tl["questions"]:
        assert q["from"] == t
        t += q["dur"]
    assert tl["outro"]["from"] == t and tl["totalFrames"] == t + tl["outro"]["dur"]


def test_fit_drops_questions_but_never_below_min():
    d = durs(10)
    per_q = timeline.build(d, 2, 3)[0]["questions"][1]["dur"] / 30
    full = timeline.build(d, 10, 3)[0]["totalFrames"] / 30
    assert timeline.fit(d, 10, 8, full, 3) == 10
    assert timeline.fit(d, 10, 8, full - per_q / 2, 3) == 9
    with pytest.raises(ValueError):
        timeline.fit(d, 10, 8, full - per_q * 2.5, 3)
