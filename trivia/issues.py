"""GitHub Issues for failures (GitHub emails the repo owner). Stdlib only, so it works even if setup failed.

Usage from the workflow:  python3 -m trivia.issues <kind> <summary>
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

SECRET_ENVS = ("CLAUDE_CODE_OAUTH_TOKEN", "IG_ACCESS_TOKEN", "IG_APP_SECRET", "GH_TOKEN", "GITHUB_TOKEN")


def redact(text: str) -> str:
    for name in SECRET_ENVS:
        v = os.environ.get(name)
        if v and len(v) >= 8:
            text = text.replace(v, "***")
    return text


def _fingerprint(title: str) -> str:
    return re.sub(r"\d+", "#", title.lower())


def open_issue(kind: str, summary: str, details: str = "") -> None:
    title = redact(f"[reels] {kind}: {summary.splitlines()[0][:90] if summary else 'failure'}")
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    body = redact(f"**Run:** {run_url}\n**Event:** {os.environ.get('GITHUB_EVENT_NAME', 'local')}\n\n```\n{summary}\n\n{details}\n```"[:60000])
    if not os.environ.get("GITHUB_ACTIONS"):
        print(f"[issue skipped locally] {title}\n{body}", file=sys.stderr)
        return
    try:
        existing = json.loads(subprocess.run(["gh", "issue", "list", "--state", "all", "--limit", "50", "--json", "title,createdAt"],
                                             capture_output=True, text=True, check=True).stdout)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for i in existing:
            if _fingerprint(i["title"]) == _fingerprint(title) and datetime.fromisoformat(i["createdAt"].replace("Z", "+00:00")) > cutoff:
                print(f"duplicate issue within 24h, not reopening: {title}", file=sys.stderr)
                return
        subprocess.run(["gh", "issue", "create", "--title", title, "--body", body], check=True)
    except Exception as e:  # never let issue reporting mask the original failure
        print(f"could not open issue: {redact(str(e))}", file=sys.stderr)


if __name__ == "__main__":
    open_issue(sys.argv[1], " ".join(sys.argv[2:]))
