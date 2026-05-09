"""Adapter for the bespoke streamable-checkers UI (built in a separate repo).

TODO: confirm against the real UI when it lands. The fields below are best-guess
defaults that should work if the UI is built CUA-friendly (clean DOM, single
board element, turn indicator, game-over banner).

Override URL via env GAME_URL_OVERRIDE or --url flag.
"""
from .base import Game


def make(url: str | None = None) -> Game:
    return Game(
        name="checkers_custom",
        url=url or "https://example.invalid/checkers",  # replaced when URL is known
        instruction=(
            "You are playing checkers as the BLACK pieces against an opponent. "
            "Look at the board and make ONE legal move by dragging one of your "
            "black pieces diagonally forward to an adjacent empty dark square, "
            "or by clicking the piece and then clicking the destination square. "
            "Make exactly one move and then stop."
        ),
        # Defaults below are placeholders. When the custom UI lands, point these
        # at the real selectors / data attributes.
        is_our_turn_js="""
            const t = document.querySelector('[data-turn], [data-active-player], .turn-indicator');
            if (!t) return true;  // no indicator ⇒ assume our turn
            const v = (t.dataset.turn || t.dataset.activePlayer || t.textContent || '').toLowerCase();
            return v.includes('black') || v.includes('you');
        """,
        game_over_js="""
            const g = document.querySelector('[data-game-over], .game-over, .winner');
            return !!g;
        """,
        state_extractor_js="",  # fill once the custom UI exposes a state hook
        max_turn_steps=15,
        poll_interval_s=1.5,
    )
