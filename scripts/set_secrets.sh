#!/usr/bin/env bash
# Store this project's secrets as GitHub Actions secrets. Run it yourself in your own terminal.
# Values are typed with hidden input, kept only in shell variables, and piped straight to `gh secret set`.
# Nothing is printed, logged or written to disk.
#
#   scripts/set_secrets.sh                            # all secrets
#   scripts/set_secrets.sh CLAUDE_CODE_OAUTH_TOKEN    # just one (e.g. the yearly Claude token renewal)
set -euo pipefail

REPO="het-dave/trivia-reels-automation"
GRAPH="https://graph.facebook.com/v27.0"
HANDLE="trivia_quiz_master"

command -v gh >/dev/null || { echo "Install the GitHub CLI first: brew install gh" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first." >&2; exit 1; }

ask() { # ask <prompt> -> value in $REPLY_SECRET (hidden input)
  local v
  printf '%s: ' "$1" >&2
  IFS= read -rs v
  printf '\n' >&2
  REPLY_SECRET="$v"
}

put() { # put <NAME> <value>   (printf is a shell builtin: the value never appears in a process list)
  printf '%s' "$2" | gh secret set "$1" --repo "$REPO" >/dev/null
  echo "  stored $1" >&2
}

graph_get() { # graph_get <token> <path?query> -> JSON on stdout. Token goes in a header read from stdin, not argv.
  printf 'Authorization: OAuth %s\n' "$1" | curl -sS --max-time 30 -H @- "$GRAPH/$2"
}

ONLY="$*"
want() { [ -z "$ONLY" ] || [[ " $ONLY " == *" $1 "* ]]; }

if want CLAUDE_CODE_OAUTH_TOKEN; then
  echo "CLAUDE_CODE_OAUTH_TOKEN: in another terminal run 'claude setup-token' and copy the token it prints (valid 1 year)." >&2
  ask "Paste CLAUDE_CODE_OAUTH_TOKEN (hidden)"
  [ -n "$REPLY_SECRET" ] && put CLAUDE_CODE_OAUTH_TOKEN "$REPLY_SECRET"
  REPLY_SECRET=""
fi

if want IG_ACCESS_TOKEN || want IG_USER_ID; then
  echo "IG_ACCESS_TOKEN: your Meta system-user token (Business Settings > System users > Generate token)." >&2
  ask "Paste IG_ACCESS_TOKEN (hidden)"
  TOKEN="$REPLY_SECRET"; REPLY_SECRET=""
  [ -n "$TOKEN" ] || { echo "No token entered, stopping." >&2; exit 1; }
  if want IG_ACCESS_TOKEN; then put IG_ACCESS_TOKEN "$TOKEN"; fi

  # Try to find the Instagram account ID automatically (needs the Page to be assigned to the system user).
  IG_ID="$(graph_get "$TOKEN" "me/accounts?fields=instagram_business_account%7Bid,username%7D&limit=100" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin).get("data", [])
except Exception:
    data = []
for page in data:
    ig = page.get("instagram_business_account") or {}
    if ig.get("username", "").lower() == sys.argv[1].lower():
        print(ig["id"])
        break
' "$HANDLE" || true)"
  if [ -n "$IG_ID" ]; then
    echo "  found Instagram account @$HANDLE automatically" >&2
  else
    echo "Couldn't look up the account ID automatically. Find it in Meta Business Settings > Accounts > Instagram accounts" >&2
    echo "(or the App Dashboard 'API setup with Facebook login' page)." >&2
    ask "Paste IG_USER_ID (hidden)"
    IG_ID="$REPLY_SECRET"; REPLY_SECRET=""
  fi
  NAME="$(graph_get "$TOKEN" "$IG_ID?fields=username" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("username",""))' 2>/dev/null || true)"
  if [ "$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]')" = "$HANDLE" ]; then
    echo "  verified: token can read @$NAME" >&2
  else
    echo "  WARNING: token/ID check did not return @$HANDLE (got '${NAME:-error}'). Check the token's permissions." >&2
  fi
  if want IG_USER_ID; then put IG_USER_ID "$IG_ID"; fi
  TOKEN=""; IG_ID=""
fi

echo "Done. Secrets in $REPO:" >&2
gh secret list --repo "$REPO" >&2
