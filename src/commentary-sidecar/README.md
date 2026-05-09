# commentary-sidecar

Standalone narrator that listens to `actuallyabot`'s stdout, asks Grok for
first-person trash-talk reactions, and speaks them via ElevenLabs.

Has no imports from any other package in this repo; the only contract is
the JSON event lines the player writes to stdout. Independent from the
`src/streambot` HTTP-event consumer — they can run together or apart.

## Setup

```bash
cp src/commentary-sidecar/.env.example src/commentary-sidecar/.env
# fill in XAI_API_KEY + ELEVENLABS_API_KEY in that .env
source .venv/bin/activate
```

No additional pip installs needed — `httpx` and `python-dotenv` are already
in the parent `pyproject.toml`.

## Run

Pipe the player's output into the sidecar:

```bash
python -u -m actuallyabot.main --game checkers_custom \
    --url "https://cua-checkers.onrender.com/?game=$(date +%s)" 2>&1 \
  | python -u src/commentary-sidecar/sidecar.py
```

The sidecar passes every line through to its stdout, so you still see the
player's logs. Commentary is logged as `[commentary] ...` /
`[commentary/filler] ...` and spoken aloud.

## When it talks

- **Turn events** — fires on `turn_end` with `reason=stop_signal` (a real
  move was made) and on `game_over`. Failed/stuck turns are skipped.
- **Filler** — every 6–14s of dead air (capped at 3 consecutive fillers
  before it shuts up until the next real event), so the agent gets to dunk
  on the opponent's slow play without droning forever.

## Audio

Plays via the first of these on `$PATH`: `afplay` (macOS built-in),
`mpg123`, `ffplay`. To route into OBS for streaming: install BlackHole
(macOS) or a virtual audio cable, set it as the system output before
launch, and add it as an Audio Input Capture in OBS.

## Tweaking the persona

Edit `SYSTEM_PROMPT` at the top of `sidecar.py`.
