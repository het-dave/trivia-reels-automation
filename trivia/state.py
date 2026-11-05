"""Repo-committed state: published log, question history, topic rotation, heartbeat."""
import json
import re
import subprocess
import time
from datetime import date
from difflib import SequenceMatcher

from .config import ROOT, STATE

PUBLISHED = "published.json"
HISTORY = "questions_history.json"
TOPICS = "topic_rotation.json"
HEARTBEAT = "heartbeat.txt"
FUZZY_DUP = 0.85


def read(name: str, default):
    p = STATE / name
    return json.loads(p.read_text()) if p.exists() else default


def write(name: str, data) -> None:
    STATE.mkdir(exist_ok=True)
    (STATE / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def pick_topic(cfg: dict, rotation: dict) -> str:
    """Least recently used topic; config order breaks ties."""
    topics = list(cfg["topics"])
    return min(topics, key=lambda t: (rotation.get(t, ""), topics.index(t)))


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def is_duplicate(question: str, topic: str, history: list[dict]) -> bool:
    """Exact match (any topic) or near-identical wording within the same topic."""
    n = norm(question)
    for h in history:
        hn = norm(h["q"])
        if hn == n:
            return True
        if h["topic"] == topic and SequenceMatcher(None, hn, n).ratio() >= FUZZY_DUP:
            return True
    return False


def record_reel(topic: str, questions: list[dict], day: date, entry: dict) -> None:
    published = read(PUBLISHED, [])
    published.append(entry)
    write(PUBLISHED, published)
    history = read(HISTORY, [])
    history += [{"date": day.isoformat(), "topic": topic, "q": q["question"], "a": q["options"][q["answer_index"]]} for q in questions]
    write(HISTORY, history)
    rotation = read(TOPICS, {})
    rotation[topic] = day.isoformat()
    write(TOPICS, rotation)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)


def commit_push(message: str, attempts: int = 5) -> None:
    """Commit state/ and push, rebasing onto any remote changes. The pre-commit secret scan runs on this commit."""
    _git("add", "state")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    _git("commit", "-m", message)
    for i in range(attempts):
        try:
            _git("pull", "--rebase")
            _git("push")
            return
        except subprocess.CalledProcessError as e:
            subprocess.run(["git", "rebase", "--abort"], cwd=ROOT, capture_output=True)
            if i == attempts - 1:
                raise RuntimeError(f"git push failed after {attempts} attempts: {e.stderr.strip()[-500:]}") from e
            time.sleep(2 ** i * 3)
