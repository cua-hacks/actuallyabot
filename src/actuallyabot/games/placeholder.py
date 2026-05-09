"""Placeholder adapter — used while the real game URL doesn't exist yet.

Run with `actuallyabot --game placeholder --url https://example.com`. Northstar
will attempt the instruction, then exit. Useful as a smoke test for the loop.
"""
from .base import Game


def make(url: str | None = None) -> Game:
    return Game(
        name="placeholder",
        url=url or "https://example.com",
        instruction=(
            "Look at this page and read the headline. When you have understood "
            "what the page says, stop."
        ),
        max_turn_steps=6,
        max_turns=1,  # smoke test: one Northstar pass and exit
    )
