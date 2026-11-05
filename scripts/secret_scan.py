#!/usr/bin/env python3
"""Fail if anything that looks like a secret is staged (--staged, pre-commit hook) or tracked (--all, CI).

Never prints the matched value: only file, line and rule name.
"""
import os
import re
import subprocess
import sys

RULES = [
    ("Anthropic / Claude OAuth token", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("Meta access token", r"\bEAA[A-Za-z0-9]{40,}"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("GitHub fine-grained PAT", r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    ("Private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("Hard-coded credential", r"(?i)\b(secret|token|passw(or)?d|api[_-]?key|client[_-]?secret)\b[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_\-./+=]{16,}[\"']"),
]
SECRET_ENVS = ("CLAUDE_CODE_OAUTH_TOKEN", "IG_ACCESS_TOKEN", "IG_APP_SECRET", "IG_APP_ID")
COMPILED = [(name, re.compile(rx)) for name, rx in RULES]


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def files(staged: bool) -> list[str]:
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z") if staged else git("ls-files", "-z")
    return [f for f in out.decode().split("\0") if f]


def content(path: str, staged: bool) -> bytes:
    if staged:
        return git("show", f":{path}")
    with open(path, "rb") as f:
        return f.read()


def main() -> int:
    staged = "--staged" in sys.argv
    exact = [(n, os.environ[n]) for n in SECRET_ENVS if len(os.environ.get(n, "")) >= 8]
    hits = []
    for path in files(staged):
        try:
            data = content(path, staged)
        except (OSError, subprocess.CalledProcessError):
            continue
        if b"\0" in data[:8000] or len(data) > 5_000_000:
            continue  # binary (fonts, media) or huge
        text = data.decode("utf-8", "replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx in COMPILED:
                if rx.search(line):
                    hits.append(f"{path}:{lineno}: looks like {name}")
            for name, value in exact:
                if value in line:
                    hits.append(f"{path}:{lineno}: contains the value of ${name}")
    if hits:
        print("SECRET SCAN FAILED - remove these before committing:", *hits, sep="\n  ", file=sys.stderr)
        return 1
    print(f"secret scan: clean ({'staged' if staged else 'all tracked'} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
