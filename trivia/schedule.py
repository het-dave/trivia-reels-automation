"""Pure slot / ramp / catch-up logic. No I/O, fully unit-tested."""
from datetime import date, datetime

EARLY_TOLERANCE_MIN = 5  # a run a few minutes before its slot time still maps to that slot


def day_index(cfg: dict, today: date) -> int | None:
    """1-based ramp day, or None if posting hasn't started (start_date unset or in the future)."""
    if not cfg.get("start_date"):
        return None
    n = (today - date.fromisoformat(str(cfg["start_date"]))).days + 1
    return n if n >= 1 else None


def active_slots(cfg: dict, day: int) -> list[int]:
    slots: list[int] = []
    for step in sorted(cfg["ramp"], key=lambda s: s["from_day"]):
        if day >= step["from_day"]:
            slots = step["slots"]
    return sorted(slots)


def current_slot(cfg: dict, now_local: datetime) -> int:
    """Latest slot whose local time has passed (0 = before the first slot)."""
    minutes = now_local.hour * 60 + now_local.minute
    slot = 0
    for i, hhmm in enumerate(cfg["slot_times_ist"], 1):
        h, m = map(int, hhmm.split(":"))
        if minutes >= h * 60 + m - EARLY_TOLERANCE_MIN:
            slot = i
    return slot


def published_on(published: list[dict], day: date) -> list[dict]:
    return [p for p in published if p["date"] == day.isoformat()]


def plan(cfg: dict, now_local: datetime, published: list[dict]) -> list[int]:
    """Slots to publish now: missed earlier active slots first, then the current one, within the daily cap."""
    today = now_local.date()
    day = day_index(cfg, today)
    if day is None:
        return []
    done_today = published_on(published, today)
    filled = {p["slot"] for p in done_today}
    cur = current_slot(cfg, now_local)
    due = [s for s in active_slots(cfg, day) if s <= cur and s not in filled]
    room = max(cfg["max_reels_per_day"] - len(done_today), 0)
    return due[:room]


def orphan_slot(cfg: dict, now_local: datetime, published: list[dict]) -> int:
    """Slot to attribute a reel found on Instagram but missing from our log (crash after publish)."""
    due = plan(cfg, now_local, published)
    return due[0] if due else 0
