import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trivia import config  # noqa: E402


@pytest.fixture
def cfg():
    c = config.load()
    c["start_date"] = "2026-11-07"
    return c
