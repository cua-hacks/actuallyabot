# actuallyabot

Player half of an AI-streamer system. A Northstar agent runs inside a Kernel
browser sandbox and plays games (starting with checkers). `src/streambot`
contains the OBS/YouTube control path for streaming that session.

## Architecture

```
this repo                                          (separate repos)
┌──────────────────────────────────┐               ┌─────────────────────────────┐
│ Kernel browser session           │               │ Streamer VM                 │
│  └─ game tab                     │ live_view ──► │  └─ OBS Browser Source ─────┼──► YouTube
│ Northstar action loop ───────────┤  CDP attach   │  └─ streambot / OBS API     │
│ orchestrator.play (game-agnostic)│ event POSTs ► │ /events endpoint            │
│ games/<name>.py adapter          │               │                             │
└──────────────────────────────────┘               └─────────────────────────────┘
```

## Contract for the streamer

On startup we log `session_id` and `browser_live_view_url`. The streamer renders
the live view URL in OBS as a Browser Source. Game-state events are POSTed to
`STREAMER_EVENT_ENDPOINT` if set, otherwise stdout only:

```json
{ "type": "turn_start" | "turn_end" | "game_over",
  "ts": 1715200000.123,
  "session_id": "...",
  "payload": { "turn": 0, "reason": "no_computer_call", "state": {...} } }
```

## Quickstart

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
cp .env.example .env  # add KERNEL_API_KEY + TZAFON_API_KEY
actuallyabot --game placeholder --url https://example.com
```

## Stream checkers to YouTube with OBS

OBS must be running locally with the WebSocket server enabled
(`Tools -> WebSocket Server Settings`, default port `4455`). Put
`OBS_WS_PASSWORD` and `STREAM_KEY` in `.env`; do not commit real keys.

One-command path for the current checkers stream:

```bash
uv run streambot-checkers-youtube
```

That command starts a local event endpoint, launches
`actuallyabot --game checkers_custom`, reads the Kernel `live_view_url` from the
player logs, creates/updates OBS Browser Source scenes, configures YouTube RTMP,
starts streaming, and switches scenes through OBS WebSocket on `turn_start`,
`turn_end`, and `game_over` events.

Manual wiring:

```bash
uv run streambot-events --host 127.0.0.1 --port 8765
STREAMER_EVENT_ENDPOINT=http://127.0.0.1:8765/events uv run actuallyabot --game checkers_custom
uv run streambot-youtube --player-live-view-url 'https://...'
```

## Adding a game

Create `src/actuallyabot/games/<name>.py` exporting `make(url=None) -> Game`.
The required fields are `url` and `instruction`; everything else is optional
(see `games/base.py` for the full Game dataclass).

```python
from .base import Game
def make(url=None):
    return Game(
        name="<name>",
        url=url or "https://...",
        instruction="...",
        is_our_turn_js="return ...;",   # optional, runs in page.evaluate
        game_over_js="return ...;",     # optional
    )
```

Then `actuallyabot --game <name>`.

## Notes

- We call Northstar (`tzafon.northstar-cua-fast`) directly via
  `Lightcone.responses.create`. Actions are executed through
  `kernel.browsers.computer.*` (no Playwright client-side).
- DOM access goes through `kernel.browsers.playwright.execute` — note that runs
  in Node, so we always wrap in `page.evaluate(() => ...)` (see `dom.py`).
- Northstar can return out-of-bounds coordinates; we clamp to viewport in
  `actions.py`. We also abort the inner loop after `STUCK_WINDOW` identical
  actions in a row.
