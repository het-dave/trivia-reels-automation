# One-time setup

Nothing here asks you to paste a secret anywhere except the hidden prompts of `scripts/set_secrets.sh` in your own terminal.

## 1. Claude token (valid 1 year)

In a terminal, run `claude setup-token`, approve in the browser, and copy the printed token. It is not saved anywhere. Keep the terminal open until step 3.

## 2. Instagram (Meta) token

The app "Trivia Reels Publisher" uses **API setup with Unified login** (Facebook Login for Business with a system-user token configuration, graph.facebook.com).
- Meta issues the token to a hidden *business integration system user*. It never expires and doesn't appear under Business Settings > System users.
- It needs **instagram_basic** and **instagram_content_publish**.
- `IG_USER_ID` is the numeric account ID, which starts with `17841` (it is not the @username). Business Settings > Accounts > Instagram accounts shows it, and the script finds it automatically via `me/assigned_instagram_accounts`.

`IG_APP_ID` and `IG_APP_SECRET` are not needed. Nothing refreshes or exchanges the token.

## 3. Store the secrets

```bash
scripts/set_secrets.sh
```

The script asks for each value with hidden input and stores it with `gh secret set` in `het-dave/trivia-reels-automation`:

- `CLAUDE_CODE_OAUTH_TOKEN`
- `IG_ACCESS_TOKEN`
- `IG_USER_ID`, looked up automatically when possible. The script then verifies the token can read @trivia_quiz_master.

## 4. Test, then go live

```bash
gh workflow run reels.yml -f mode=dry_run        # renders on GitHub, uploads the MP4 as an artifact
gh workflow run reels.yml -f mode=publish_test   # posts one real reel
```

After the test reel is live, set that account's `start_date` under `accounts` in `config.yaml` to the next day and push. From then on everything is automatic:

- Days 1-14: 2 reels/day.
- From day 15: 4 reels/day.

## Adding an Instagram account

1. Make it a Professional account, add it to the business portfolio, and assign it to the app's token (see section 2).
2. Add it under `accounts` in `config.yaml` (next free `secret_suffix`, slot times on :17/:47 not used by another account, a different `topic_shift`, `start_date: null`) and to the matrix in `.github/workflows/reels.yml`.
3. `scripts/set_secrets.sh <handle>` (or `scripts/set_secrets.sh <handle> IG_USER_ID` when the existing token already covers it).
4. `gh workflow run reels.yml -f mode=check_ig -f account=<handle>`, then `-f mode=dry_run`, then `-f mode=publish_test`; then set `start_date`.

## 5. Wake-up trigger (Cloudflare Worker)

GitHub's own schedule never fired for this repo, so a free Cloudflare Worker starts the workflow every 30 min.
Create a fine-grained token at github.com/settings/personal-access-tokens/new: Repository access > Only select
repositories > `het-dave/trivia-reels-automation`; Repository permissions > Actions: Read and write; the longest
expiration offered. Then run (logs in to Cloudflare if needed, deploys the Worker, stores the token with hidden input):

```bash
scripts/set_trigger.sh
```

## Yearly

The Claude token expires one year after it was created. You'll get a GitHub Issue when runs start failing. Renew with:

```bash
claude setup-token
scripts/set_secrets.sh CLAUDE_CODE_OAUTH_TOKEN
```

When the trigger's GitHub token expires (GitHub emails you a week before), create a new one as in step 5 and run `scripts/set_trigger.sh` again.

## Good to know

- Failures open GitHub Issues, which GitHub emails you. Make sure notifications are on for this repo (Watch > Participating).
- To pause posting, set the account's `start_date: null` and push. To stop the workflow entirely: `gh workflow disable reels.yml`.
- Royalty-free music dropped into `assets/music/` is used automatically, at -25 dB and ducked under speech.
