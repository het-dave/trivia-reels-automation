import re

import pytest

from trivia import config, state

HANDLES = config.load()["all_handles"]
WORKFLOW = (config.ROOT / ".github" / "workflows" / "reels.yml").read_text()


def test_handles_unique_and_state_dirs_distinct():
    assert len(set(HANDLES)) == len(HANDLES) >= 3
    assert len({config.state_dir(h) for h in HANDLES}) == len(HANDLES)


@pytest.mark.parametrize("handle", HANDLES)
def test_slot_times_on_wake_minutes(handle):
    cfg = config.load(account=handle)
    assert cfg["account_handle"] == handle
    assert all(t[3:] in ("17", "47") for t in cfg["slot_times_ist"])  # the workflow wakes at :17 and :47 IST


def test_slot_times_never_collide_across_accounts():
    times = [t for h in HANDLES for t in config.load(account=h)["slot_times_ist"]]
    assert len(set(times)) == len(times)


def test_workflow_matrix_matches_config():
    raw = config.yaml.safe_load((config.ROOT / "config.yaml").read_text())["accounts"]
    for a in raw:
        assert re.search(rf'handle: {re.escape(a["handle"])}, suffix: "{a["secret_suffix"]}"', WORKFLOW), a["handle"]
    assert WORKFLOW.count("- {handle:") == len(raw)


def test_topic_shift_gives_each_account_a_different_first_topic():
    firsts = [state.pick_topic(config.load(account=h), {}) for h in HANDLES]
    assert len(set(firsts)) == len(firsts)


def test_pick_topic_still_least_recently_used():
    cfg = config.load(account=HANDLES[1])
    first = state.pick_topic(cfg, {})
    assert state.pick_topic(cfg, {first: "2026-11-07"}) != first
