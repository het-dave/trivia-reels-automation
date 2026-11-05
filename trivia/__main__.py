"""CLI.

  python -m trivia gate                          # scheduled runs: is any slot due? (+ daily heartbeat commit)
  python -m trivia run --mode schedule           # catch-up + current slot, publish
  python -m trivia run --mode dry_run [--topic Space] [--force-piper]   # render only, no state, no posting
  python -m trivia run --mode publish_test       # publish one real reel now
"""
import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import config, schedule, state
from .issues import open_issue, redact

T0 = time.time()


class ValidationFailed(RuntimeError):
    pass


def log(msg: str) -> None:
    print(redact(msg), flush=True)


def summary(md: str) -> None:
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(md + "\n")


def narration(topic: str, qs: list[dict], n_min: int) -> dict[str, str]:
    lines = {f"hook{n}": f"Can you score {n} out of {n}? Today's topic: {topic}!" for n in range(n_min, len(qs) + 1)}
    for i, q in enumerate(qs):
        lines[f"q{i}"] = q["question"]
        for k, o in enumerate(q["options"]):
            lines[f"q{i}o{k}"] = f"{'ABCD'[k]}: {o}."
        a = q["answer_index"]
        lines[f"r{i}"] = f"The answer is {'ABCD'[a]}, {q['options'][a]}. {q['fun_fact']}"
    lines["outro"] = "Comment your score! Follow for daily trivia."
    return lines


def produce(cfg: dict, topic: str, seed: str, force_piper: bool) -> dict:
    from . import audio, questions, render, timeline, tts, validate

    work = config.OUT / seed
    work.mkdir(parents=True, exist_ok=True)
    log(f"[1/5] questions: {topic}")
    qs = questions.get_questions(cfg, topic, state.read(state.HISTORY, []), seed, log)
    log(f"[2/5] voiceover ({len(qs)} questions)")
    n_min = cfg["questions"]["min"]
    engine, durs = tts.synthesize(narration(topic, qs, n_min), work / "clips", cfg, force_piper, log)
    log(f"  engine: {engine}")
    n = timeline.fit(durs, len(qs), n_min, cfg["max_duration_seconds"], cfg["timer_seconds"])
    qs = qs[:n]
    tl, events = timeline.build(durs, n, cfg["timer_seconds"])
    log(f"[3/5] mix: {n} questions, {tl['totalFrames'] / tl['fps']:.1f}s")
    audio.mix(events, tl, work / "clips", cfg, work / "master.wav", seed)
    cap = questions.caption(cfg, topic, n)
    props = {
        "topic": topic, "handle": cfg["account_handle"], "palette": cfg["topics"][topic], "audio": None, "timeline": tl,
        "questions": [{"question": q["question"], "options": q["options"], "answerIndex": q["answer_index"], "funFact": q["fun_fact"]} for q in qs],
    }
    log("[4/5] render")
    mp4 = config.OUT / f"{seed}.mp4"
    secs = render.render(props, work / "master.wav", mp4, cfg, log)
    log("[5/5] validate")
    errors = validate.validate(mp4, work / "speech_stem.wav", tl, events, n, cap, cfg)
    if errors:
        raise ValidationFailed("; ".join(errors))
    (work / "caption.txt").write_text(cap)
    return {"mp4": mp4, "caption": cap, "questions": qs, "engine": engine, "render_s": round(secs), "duration_s": round(tl["totalFrames"] / tl["fps"], 1)}


def reconcile(ig, cfg: dict, now: datetime, published: list[dict]) -> list[dict]:
    """Reels on the account today that our log doesn't know about (crash between publish and commit)."""
    known = {p.get("media_id") for p in published}
    marker = f"@{cfg['account_handle']}"
    found = []
    for m in ig.recent_media():
        if m["id"] in known or marker not in (m.get("caption") or ""):
            continue
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(now.tzinfo)
        if ts.date() == now.date():
            slot = schedule.orphan_slot(cfg, now, published + found)
            found.append({"date": ts.date().isoformat(), "slot": slot, "kind": "reconciled", "media_id": m["id"], "published_at": m["timestamp"]})
    return found


def publish_one(cfg: dict, ig, slot: int, kind: str, force_piper: bool) -> None:
    today = config.now(cfg).date()
    topic = state.pick_topic(cfg, state.read(state.TOPICS, {}))
    seed = f"{today.isoformat()}-s{slot}-{topic.lower()}"
    reel = produce(cfg, topic, seed, force_piper)
    log(f"publishing slot {slot}: {topic}")
    res = ig.publish_reel(reel["mp4"], reel["caption"], cfg, log)
    entry = {"date": today.isoformat(), "slot": slot, "kind": kind, "topic": topic, "questions": len(reel["questions"]),
             "engine": reel["engine"], "duration_s": reel["duration_s"], "render_s": reel["render_s"],
             "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **res}
    # Log + commit immediately after media_publish so a later crash can't cause a double post.
    state.record_reel(topic, reel["questions"], today, entry)
    state.commit_push(f"state: published {today} slot {slot} ({topic})")
    log(f"published {res['permalink'] or res['media_id']}")
    summary(f"| {kind} slot {slot} | {topic} | {entry['questions']} Qs | {entry['duration_s']}s | {entry['engine']} | render {entry['render_s']}s | {res['permalink']} |")


def cmd_gate(cfg: dict) -> int:
    now = config.now(cfg)
    due = schedule.plan(cfg, now, state.read(state.PUBLISHED, []))
    hb = config.STATE / state.HEARTBEAT
    if not hb.exists() or hb.read_text().strip() != now.date().isoformat():
        hb.write_text(now.date().isoformat() + "\n")  # keeps the repo "active" so GitHub never disables the schedule
        state.commit_push(f"state: heartbeat {now.date()}")
    log(f"{now:%Y-%m-%d %H:%M %Z}: slot {schedule.current_slot(cfg, now)}, due {due or 'nothing'}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"work={'true' if due else 'false'}\n")
    return 0


def cmd_run(cfg: dict, mode: str, topic: str | None, force_piper: bool) -> int:
    from .instagram import IG, AuthError
    from .tts import TTSFailed

    if mode == "dry_run":
        now = config.now(cfg)
        topic = topic or state.pick_topic(cfg, state.read(state.TOPICS, {}))
        reel = produce(cfg, topic, f"dryrun-{now:%Y%m%d-%H%M}-{topic.lower()}", force_piper)
        log(f"\nDRY RUN OK: {reel['mp4']}\n  engine={reel['engine']} questions={len(reel['questions'])} duration={reel['duration_s']}s render={reel['render_s']}s\n\n{reel['caption']}")
        summary(f"### Dry run\n- TTS engine: **{reel['engine']}**\n- Remotion render: **{reel['render_s']}s**\n- {len(reel['questions'])} questions, {reel['duration_s']}s\n\n```\n{reel['caption']}\n```")
        return 0

    ig = IG(os.environ.get("IG_ACCESS_TOKEN", ""), os.environ.get("IG_USER_ID", ""), cfg["instagram"]["graph_version"])
    summary("| run | topic | questions | length | voice | render | link |\n|---|---|---|---|---|---|---|")
    if mode == "publish_test":
        publish_one(cfg, ig, 0, "test", force_piper)
        return 0

    now = config.now(cfg)
    published = state.read(state.PUBLISHED, [])
    orphans = reconcile(ig, cfg, now, published)
    if orphans:
        log(f"reconciled {len(orphans)} reel(s) missing from the log: {[o['media_id'] for o in orphans]}")
        state.write(state.PUBLISHED, published + orphans)
        state.commit_push(f"state: reconcile {now.date()}")
    todo = schedule.plan(cfg, now, state.read(state.PUBLISHED, []))
    log(f"slot {schedule.current_slot(cfg, now)}; to publish now: {todo or 'nothing'}")
    failed = 0
    for slot in todo:
        if (time.time() - T0) / 60 + cfg["reel_minutes_estimate"] > cfg["run_budget_minutes"]:
            log(f"time budget reached, slot {slot} left for the next run")
            break
        try:
            publish_one(cfg, ig, slot, "scheduled", force_piper)
        except AuthError:
            raise
        except Exception as e:
            failed += 1
            log(traceback.format_exc())
            open_issue(f"slot {slot} skipped", f"{type(e).__name__}: {e}", traceback.format_exc())
            if isinstance(e, TTSFailed):
                break
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(prog="trivia")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gate")
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=["schedule", "dry_run", "publish_test"], required=True)
    r.add_argument("--topic")
    r.add_argument("--force-piper", action="store_true")
    a = p.parse_args()
    try:
        cfg = config.load()
        if a.cmd == "gate":
            return cmd_gate(cfg)
        if a.topic and a.topic not in cfg["topics"]:
            p.error(f"unknown topic {a.topic}; choose from {', '.join(cfg['topics'])}")
        return cmd_run(cfg, a.mode, a.topic, a.force_piper)
    except Exception as e:
        from .instagram import AuthError

        kind = "auth error (run skipped)" if isinstance(e, AuthError) else f"{getattr(a, 'mode', a.cmd)} failed"
        log(traceback.format_exc())
        open_issue(kind, f"{type(e).__name__}: {e}", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
