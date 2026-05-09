# actuallyabot

Player half of an AI-streamer system. A Northstar agent runs inside a Kernel
browser sandbox and plays games (starting with checkers). Streaming, OBS,
Twitch, and commentary live in a separate repo.

## Architecture

```
this repo                                          (separate repos)
┌──────────────────────────────────┐               ┌─────────────────────────────┐
│ Kernel browser session           │               │ Streamer VM                 │
│  └─ game tab                     │ live_view ──► │  └─ OBS Browser Source ─────┼──► Twitch
│ Northstar action loop ───────────┤  CDP attach   │  └─ commentary / scenes     │
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
