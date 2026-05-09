"""Game adapter contract.

Each adapter is one Python module under games/. The minimum required is a URL
and an INSTRUCTION; the rest are optional knobs the orchestrator uses if present.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Game:
    name: str
    url: str
    # Per-turn instruction handed to Northstar. Phrase as imperative; the model
    # is action-biased and will not "answer" in text.
    instruction: str
    # Optional JS bodies (run inside `page.evaluate(() => {...})`).
    # Empty string means "skip this step".
    preflight_js: str = ""           # one-shot DOM cleanup after navigation
    is_our_turn_js: str = ""         # returns boolean; absent ⇒ always true
    game_over_js: str = ""           # returns boolean; absent ⇒ never
    state_extractor_js: str = ""     # returns JSON-serializable state for events
    # Per-turn limits for the inner Northstar loop.
    max_turn_steps: int = 12
    poll_interval_s: float = 1.0     # how often to poll IS_OUR_TURN / GAME_OVER
    # Cap the orchestrator's outer loop. None = play until game_over_js fires.
    # Set explicitly (e.g. 1) for smoke-test adapters that have no game-over.
    max_turns: int | None = None
