from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
OUT = ROOT / "out"
REMOTION = ROOT / "remotion"
MUSIC = ROOT / "assets" / "music"


def load(path: Path = ROOT / "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def now(cfg: dict) -> datetime:
    return datetime.now(ZoneInfo(cfg["timezone"]))
