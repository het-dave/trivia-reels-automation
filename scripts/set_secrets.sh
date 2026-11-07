#!/usr/bin/env bash
# Store this project's secrets as GitHub Actions secrets. Run it yourself in your own terminal.
# Values are typed with hidden input, kept only in shell variables, and piped straight to `gh secret set`.
# Nothing is printed, logged or written to disk.
#
#   scripts/set_secrets.sh                            # all secrets for @trivia_quiz_master
#   scripts/set_secrets.sh CLAUDE_CODE_OAUTH_TOKEN    # just one (e.g. the yearly Claude token renewal)
#   scripts/set_secrets.sh triviaquizmaster           # another account (handle from config.yaml): its IG_ACCESS_TOKEN_2 + IG_USER_ID_2
#   scripts/set_secrets.sh triviaquizmaster IG_USER_ID  # only its account ID (when one token covers several accounts)
set -euo pipefail
cd "$(dirname "$0")/.."

REPO="het-dave/trivia-reels-automation"
GRAPH="https://graph.facebook.com/v27.0"
HANDLE="trivia_quiz_master"
SUFFIX=""
if [ $# -gt 0 ] && [[ "$1" =~ ^[a-z0-9._]+$ ]]; then  # first argument is an account handle (secret names are UPPER_CASE)
  HANDLE="$1"; shift
  LINE="$(grep -F "handle: $HANDLE," config.yaml || true)"
  [ -n "$LINE" ] || { echo "No account '$HANDLE' in config.yaml." >&2; exit 1; }
  SUFFIX="$(printf '%s' "$LINE" | sed -E 's/.*secret_suffix: "([^"]*)".*/\1/')"
  [ $# -gt 0 ] || set -- IG_ACCESS_TOKEN IG_USER_ID  # the Claude token is shared: not asked again per account
fi

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

if [ "$ONLY" = "IG_USER_ID" ]; then
  # Just the account ID: it's all digits and starts with 17841 (Business Settings > Accounts > Instagram accounts).
  ask "Paste IG_USER_ID, the 17841... number (hidden)"
  IG_ID="$(printf '%s' "$REPLY_SECRET" | tr -cd '0-9')"; REPLY_SECRET=""
  case "$IG_ID" in 17841*) put "IG_USER_ID$SUFFIX" "$IG_ID" ;; *) echo "That isn't an Instagram account ID (all digits, starts with 17841). Nothing stored." >&2; exit 1 ;; esac
  echo "  verify with: gh workflow run reels.yml -f mode=check_ig -f account=$HANDLE" >&2
elif want IG_ACCESS_TOKEN || want IG_USER_ID; then
  echo "IG_ACCESS_TOKEN: the never-expiring token from your app's 'API setup with Unified login'." >&2
  ask "Paste IG_ACCESS_TOKEN (hidden)"
  TOKEN="$REPLY_SECRET"; REPLY_SECRET=""
  [ -n "$TOKEN" ] || { echo "No token entered, stopping." >&2; exit 1; }
  if want IG_ACCESS_TOKEN; then put "IG_ACCESS_TOKEN$SUFFIX" "$TOKEN"; fi

  # Find the account ID: Unified-login tokens list it under me/assigned_instagram_accounts; Page tokens under me/accounts.
  FIND='
import json, sys
try:
    data = json.load(sys.stdin).get("data", [])
except Exception:
    data = []
for item in data:
    ig = item.get("instagram_business_account") or item
    if ig.get("username", "").lower() == sys.argv[1].lower():
        print(ig["id"])
        break
'
  IG_ID="$(graph_get "$TOKEN" "me/assigned_instagram_accounts?fields=id,username&limit=100" | python3 -c "$FIND" "$HANDLE" || true)"
  [ -n "$IG_ID" ] || IG_ID="$(graph_get "$TOKEN" "me/accounts?fields=instagram_business_account%7Bid,username%7D&limit=100" | python3 -c "$FIND" "$HANDLE" || true)"
  if [ -n "$IG_ID" ]; then
    echo "  found @$HANDLE automatically" >&2
  else
    echo "Couldn't find @$HANDLE with this token. Its ID (all digits, starts with 17841) is in" >&2
    echo "Meta Business Settings > Accounts > Instagram accounts." >&2
    ask "Paste IG_USER_ID (hidden)"
    IG_ID="$(printf '%s' "$REPLY_SECRET" | tr -cd '0-9')"; REPLY_SECRET=""
  fi
  NAME="$(graph_get "$TOKEN" "$IG_ID?fields=username" | python3 -c '
import json, sys
try:
    r = json.load(sys.stdin)
except Exception:
    r = {}
e = r.get("error", {})
print(r.get("username") or "ERROR: %s (code %s, subcode %s)" % (e.get("message", "no response"), e.get("code"), e.get("error_subcode")))
' 2>/dev/null || true)"
  if [ "$(printf '%s' "$NAME" | tr '[:upper:]' '[:lower:]')" = "$HANDLE" ]; then
    echo "  verified: token can read @$NAME" >&2
  else
    echo "  WARNING: token/ID check did not return @$HANDLE. Meta said: $NAME" >&2
    echo "  Diagnose with: gh workflow run reels.yml -f mode=check_ig -f account=$HANDLE" >&2
  fi
  if want IG_USER_ID; then put "IG_USER_ID$SUFFIX" "$IG_ID"; fi
  TOKEN=""; IG_ID=""
fi

echo "Done. Secrets in $REPO:" >&2
gh secret list --repo "$REPO" >&2
