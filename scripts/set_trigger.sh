#!/usr/bin/env bash
# Deploy the Cloudflare Worker that wakes the reels workflow every 30 min, and store its GitHub token.
# Run it yourself in your own terminal. Re-run it when the token expires (GitHub emails you a week before).
#
# The token: github.com/settings/personal-access-tokens/new -> Repository access: Only select repositories ->
# het-dave/trivia-reels-automation -> Repository permissions -> Actions: Read and write. Nothing else.
# It is typed with hidden input, checked against GitHub, and piped straight to `wrangler secret put`.
set -euo pipefail

REPO="het-dave/trivia-reels-automation"
WRANGLER=(npx -y wrangler@4.151.3)
cd "$(dirname "$0")/../trigger"

"${WRANGLER[@]}" whoami 2>/dev/null | grep -qi "logged in" || "${WRANGLER[@]}" login

printf 'GitHub token (Actions: Read and write on %s only, input hidden): ' "$REPO" >&2
IFS= read -rs TOKEN
printf '\n' >&2
code=$(printf 'Authorization: Bearer %s\n' "$TOKEN" | curl -s -o /dev/null -w '%{http_code}' -H @- \
  -H 'Accept: application/vnd.github+json' "https://api.github.com/repos/$REPO/actions/workflows/reels.yml")
[ "$code" = 200 ] || { echo "GitHub rejected the token for $REPO (HTTP $code): check its repository access and Actions permission." >&2; exit 1; }

"${WRANGLER[@]}" deploy
printf '%s' "$TOKEN" | "${WRANGLER[@]}" secret put GH_DISPATCH_TOKEN
unset TOKEN
echo "Done: the Worker wakes the reels workflow at :17 and :47 past every hour (UTC)." >&2
