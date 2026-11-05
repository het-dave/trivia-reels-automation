# One-time setup

Nothing here asks you to paste a secret anywhere except the hidden prompts of `scripts/set_secrets.sh` in your own terminal.

## 1. Claude token (valid 1 year)

In a terminal, run `claude setup-token`, approve in the browser, and copy the printed token. It is not saved anywhere. Keep the terminal open until step 3.

## 2. Instagram (Meta) token

Your app uses **API setup with Facebook Login** (graph.facebook.com). You need:

- **@trivia_quiz_master** is a Professional (Business or Creator) account linked to a Facebook Page.
- In Business Settings > System users, a system user assigned to that Page and Instagram account and to your app.
- A token for that system user with **instagram_basic** and **instagram_content_publish**, expiry "Never".
  - Optionally add `pages_show_list` so step 3 can find the Instagram account ID automatically. Otherwise you'll be asked to paste it.

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

After the test reel is live, set `start_date` in `config.yaml` to the next day and push. From then on everything is automatic:

- Days 1-14: 2 reels/day.
- From day 15: 4 reels/day.

## Yearly

The Claude token expires one year after it was created. You'll get a GitHub Issue when runs start failing. Renew with:

```bash
claude setup-token
scripts/set_secrets.sh CLAUDE_CODE_OAUTH_TOKEN
```

## Good to know

- Failures open GitHub Issues, which GitHub emails you. Make sure notifications are on for this repo (Watch > Participating).
- To pause posting, set `start_date: null` and push. To stop the workflow entirely: `gh workflow disable reels.yml`.
- Royalty-free music dropped into `assets/music/` is used automatically, at -25 dB and ducked under speech.
