import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
REMOTION = ROOT / "remotion"
MUSIC = ROOT / "assets" / "music"


def load(path: Path = ROOT / "config.yaml", account: str | None = None) -> dict:
    """Top-level keys are shared defaults; the selected account's entry in `accounts` overrides them.
    Account = argument, else env TRIVIA_ACCOUNT (set per matrix job in CI), else the first account listed."""
    cfg = yaml.safe_load(Path(path).read_text())
    accounts = cfg.pop("accounts")
    handle = account or os.environ.get("TRIVIA_ACCOUNT") or accounts[0]["handle"]
    mine = next((a for a in accounts if a["handle"] == handle), None)
    if mine is None:
        raise SystemExit(f"unknown account {handle!r}; configured: {', '.join(a['handle'] for a in accounts)}")
    return {**cfg, **mine, "account_handle": handle, "all_handles": [a["handle"] for a in accounts]}


def state_dir(handle: str) -> Path:
    return ROOT / "state" / handle


ACCOUNT = load()["account_handle"]
STATE = state_dir(ACCOUNT)


def now(cfg: dict) -> datetime:
    return datetime.now(ZoneInfo(cfg["timezone"]))
