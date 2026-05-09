"""Adapter for the bespoke CUA-checkers UI.

URL: https://cua-checkers-production.up.railway.app/

Selectors verified live:
- Role:     [data-testid="role-header"]   text "YOU ARE RED" / "YOU ARE BLACK"
- Turn:     #status                       class is "black" or "red" + text "<COLOR> TO MOVE"
- Squares:  [data-square="<alg>"]         id="sq-<alg>"; data-piece="empty"|"red"|"black"|kings
- Buttons:  #reset (New Game), #undo, #copy-state

Role assignment: WebSocket join order. First to connect = RED, second = BLACK.
The agent launches first → it plays RED. RED moves first in standard checkers
so the agent makes the opening move.
"""
from .base import Game


def make(url: str | None = None) -> Game:
    return Game(
        name="checkers_custom",
        url=url or "https://cua-checkers-production.up.railway.app/",
        instruction=(
            "You are playing checkers as the RED pieces. The board is in the "
            "center of the screen with squares labeled a-h horizontally and 1-8 "
            "vertically. The status panel on the side shows whose turn it is. "
            "Make ONE legal move: click one of your red pieces and then click "
            "the destination square (diagonally forward to an adjacent empty "
            "dark square, or further if it's a capture). After your move "
            "completes, stop."
        ),
        # It's our turn when the #status element's class matches our color.
        # Returns true if status div has class "red".
        is_our_turn_js="""
            const s = document.getElementById('status');
            if (!s) return false;
            return s.classList.contains('red');
        """,
        # Game-over when the status text mentions a winner or draw. This is a
        # heuristic — refine once we observe the actual game-end DOM.
        game_over_js="""
            const s = document.getElementById('status');
            if (!s) return false;
            const t = (s.innerText || '').toUpperCase();
            return /WINS|WINNER|DRAW|GAME OVER/.test(t);
        """,
        state_extractor_js="",  # streamer reads state from the game's REST/WS API
        max_turn_steps=15,
        poll_interval_s=1.0,
    )
