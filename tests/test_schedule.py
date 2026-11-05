from datetime import date, datetime
from zoneinfo import ZoneInfo

from trivia import schedule

IST = ZoneInfo("Asia/Kolkata")


def at(d, hh, mm):
    return datetime(2026, 11, d, hh, mm, tzinfo=IST)


def pub(d, slot):
    return {"date": f"2026-11-{d:02d}", "slot": slot, "media_id": f"m{d}{slot}"}


def test_not_started_or_unset(cfg):
    assert schedule.plan(cfg, at(6, 21, 0), []) == []  # day before start_date
    cfg["start_date"] = None
    assert schedule.plan(cfg, at(20, 21, 0), []) == []


def test_ramp(cfg):
    assert schedule.day_index(cfg, date(2026, 11, 7)) == 1
    assert schedule.active_slots(cfg, 1) == [2, 4]
    assert schedule.active_slots(cfg, 14) == [2, 4]
    assert schedule.active_slots(cfg, 15) == [1, 2, 3, 4]


def test_slot_mapping_tolerates_cron_delay(cfg):
    assert schedule.current_slot(cfg, at(7, 8, 0)) == 0
    assert schedule.current_slot(cfg, at(7, 8, 47)) == 1
    assert schedule.current_slot(cfg, at(7, 12, 44)) == 2  # 3 min early is fine
    assert schedule.current_slot(cfg, at(7, 14, 30)) == 2  # cron ran late
    assert schedule.current_slot(cfg, at(7, 20, 50)) == 4


def test_inactive_slot_does_nothing(cfg):
    assert schedule.plan(cfg, at(7, 8, 50), []) == []  # slot 1 inactive during ramp days 1-14
    assert schedule.plan(cfg, at(7, 17, 0), [pub(7, 2)]) == []  # slot 3 inactive, slot 2 done


def test_current_slot_due(cfg):
    assert schedule.plan(cfg, at(7, 12, 50), []) == [2]


def test_catch_up_earlier_slot_first(cfg):
    assert schedule.plan(cfg, at(7, 20, 50), []) == [2, 4]  # slot 2 was missed
    assert schedule.plan(cfg, at(7, 20, 50), [pub(7, 2)]) == [4]
    assert schedule.plan(cfg, at(22, 16, 50), [pub(22, 1)]) == [2, 3]  # day 16, 4/day
    assert schedule.plan(cfg, at(7, 20, 50), [pub(6, 2), pub(6, 4)]) == [2, 4]  # yesterday doesn't count


def test_daily_cap(cfg):
    cfg["max_reels_per_day"] = 3
    done = [pub(22, 1), pub(22, 2)]
    assert schedule.plan(cfg, at(22, 20, 50), done) == [3]  # only one left under the cap
    done.append({"date": "2026-11-22", "slot": 0, "media_id": "test"})  # publish_test counts toward the cap
    assert schedule.plan(cfg, at(22, 20, 50), done) == []


def test_orphan_gets_earliest_unfilled_slot(cfg):
    assert schedule.orphan_slot(cfg, at(7, 20, 50), []) == 2
    assert schedule.orphan_slot(cfg, at(7, 20, 50), [pub(7, 2), pub(7, 4)]) == 0
