# trivia-reels-automation

Generates and publishes narrated trivia Reels to Instagram [@trivia_quiz_master](https://instagram.com/trivia_quiz_master) on a schedule, with no manual steps after setup. Runs on free GitHub Actions minutes (public repo). The only paid component is a Claude subscription.

## What each run does

```
slot gate -> reconcile log with Instagram -> pick topic (least recently used)
-> claude -p: generate 14 candidates -> claude -p: fact-check -> dedupe vs history
-> voiceover (edge-tts, Piper fallback) -> frame timeline from measured speech
-> master audio mix (narration + tick/ding/whoosh + ducked music, -14 LUFS)
-> Remotion render (1080x1920, 30fps, H.264/AAC) -> validate -> publish -> commit state
```

- **Schedule:** `17 3,7,11,15 * * *` UTC = 08:47 / 12:47 / 16:47 / 20:47 IST = slots 1-4. From `start_date` (2026-11-06) all four slots post, 4 reels/day (the `ramp` in config.yaml can stage this). Inactive slots exit in about 15 seconds.
- **Catch-up:** a missed earlier slot today is filled first, then the current slot. Both respect `max_reels_per_day` and the run's time budget.
- **No double posts:** the log is committed right after `media_publish`. Each run also reconciles the log against the account's recent media.
- **Voiceover is mandatory.** If edge-tts and Piper both fail, the slot is skipped and an Issue is opened. The validator rejects any reel without narration at the expected timestamps.
- **Failures** skip the slot and open a GitHub Issue (GitHub emails you). The same failure is reported at most once per 24 hours.

## Reel format

Hook ("Can you score N out of N? Today's topic: X!") -> 8-10 questions -> outro ("Comment your score! Follow for daily trivia.").

Each question runs in this order:
1. The question is read.
2. Options A-D slide in as each one is read.
3. A 3-second gold countdown ring runs with ticks only.
4. A ding plays and the correct option turns green.
5. "The answer is B, Saturn." plus a one-line fun fact.

Python measures every speech clip and builds an exact frame timeline. Remotion only places scenes at those frames and plays one pre-mixed audio file. Reels are capped at 180s (Instagram's in-app Reel limit). Questions are dropped to fit, never below 8, and the voice is never sped up.

## Layout

| Path | What |
|---|---|
| `config.yaml` | Schedule, ramp, topics and palettes, voices, mix levels, models |
| `trivia/` | Python orchestrator (`python -m trivia ...`) |
| `remotion/` | `QuizReel` composition (React + TypeScript, Remotion 4.0.541 pinned) |
| `state/` | Published log, question history, topic rotation, heartbeat (committed by the bot) |
| `.github/workflows/reels.yml` | The only workflow (schedule + manual dispatch) |
| `scripts/set_secrets.sh` | Stores secrets with `gh secret set` (hidden input) |
| `scripts/secret_scan.py`, `.githooks/pre-commit` | Block secrets from being committed (local hook + CI step) |
| `assets/music/` | Optional royalty-free music. If empty, a synthesized ambient bed is used |

## Local commands

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
(cd remotion && npm ci)
git config core.hooksPath .githooks                 # enable the secret-scan pre-commit hook

.venv/bin/python -m trivia run --mode dry_run                 # full pipeline, writes out/<name>.mp4, posts nothing
.venv/bin/python -m trivia run --mode dry_run --topic Space   # pick the topic
.venv/bin/python -m pytest tests                              # tests

cd remotion && npm run studio                                    # preview the sample in Remotion Studio
cd remotion && npx remotion studio src/index.ts --props=public/run/props.json   # preview the last local render, with audio
```

Local runs use your logged-in `claude` CLI and need `ffmpeg` installed.

## Manual runs on GitHub

```bash
gh workflow run reels.yml -f mode=dry_run                 # render only, MP4 attached to the run as an artifact
gh workflow run reels.yml -f mode=dry_run -f force_piper=true   # test the Piper fallback
gh workflow run reels.yml -f mode=publish_test            # publish one real reel now
gh workflow run reels.yml -f mode=check_ig                # verify the Instagram token, permissions and account ID
```

The job summary shows the TTS engine used, render time, length and permalink.

## Licenses

- **Remotion** is not MIT. It's free for individuals, for-profit organizations with up to 3 employees, and non-profits. Larger for-profit companies need a paid Company License. See [remotion.dev/license](https://remotion.dev/license).
- **Fonts:** Poppins, SIL Open Font License (`remotion/public/fonts/OFL.txt`).
- **Sound effects and default music** are synthesized in code (`trivia/audio.py`), so no licensing applies.
- **Voices:** edge-tts uses Microsoft Edge's online neural voices (an unofficial client). Piper `en_US-ryan-high` is an open voice model.
