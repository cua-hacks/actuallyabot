# commentary-sidecar

Standalone narrator that listens to `actuallyabot`'s stdout, asks Grok for
first-person trash-talk reactions, and speaks them via ElevenLabs.

Lives in this repo for convenience while the streamer-side service doesn't
exist yet — designed to be lifted into its own repo when that lands. No
imports from `src/actuallyabot`; the only contract is the JSON event lines
the player writes to stdout.

## Setup

```bash
cd commentary-sidecar
cp .env.example .env  # fill in XAI_API_KEY + ELEVENLABS_API_KEY
# Reuse the parent project's venv (already has httpx + python-dotenv):
source ../.venv/bin/activate
```

No additional pip installs needed — `httpx` and `python-dotenv` are already
in the parent `pyproject.toml`.

## Run

Pipe the player's output into the sidecar:

```bash
python -u -m actuallyabot.main --game checkers_custom \
    --url "https://cua-checkers.onrender.com/?game=$(date +%s)" 2>&1 \
  | python -u commentary-sidecar/sidecar.py
```

The sidecar passes every line through to its stdout, so you still see the
player's logs. Commentary is logged as `[commentary] ...` /
`[commentary/filler] ...` and spoken aloud.

## When it talks

- **Turn events** — fires on `turn_end` with `reason=stop_signal` (a real
  move was made) and on `game_over`. Failed/stuck turns are skipped.
- **Filler** — every 3–5s of dead air (capped at 3 consecutive fillers
  before it shuts up until the next real event), so the agent gets to dunk
  on the opponent's slow play without droning forever.

## Audio

Plays via the first of these on `$PATH`: `afplay` (macOS built-in),
`mpg123`, `ffplay`. To route into OBS for streaming: install BlackHole
(macOS) or a virtual audio cable, set it as the system output before
launch, and add it as an Audio Input Capture in OBS.

## Tweaking the persona

Edit `SYSTEM_PROMPT` at the top of `sidecar.py`.
