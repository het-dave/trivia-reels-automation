import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trivia import config  # noqa: E402


@pytest.fixture
def cfg():
    c = config.load()
    # Pin schedule settings so tests don't depend on the live config.
    c["start_date"] = "2026-11-07"
    c["ramp"] = [{"from_day": 1, "slots": [2, 4]}, {"from_day": 15, "slots": [1, 2, 3, 4]}]
    c["max_reels_per_day"] = 4
    return c
