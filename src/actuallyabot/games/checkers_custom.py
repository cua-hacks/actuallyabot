"""Adapter for the bespoke CUA-checkers UI.

URL: https://cua-checkers.onrender.com/

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
        url=url or "https://cua-checkers.onrender.com/",
        instruction=(
            "You are playing checkers as RED. Your red pieces are on the bottom "
            "three rows (rows 1, 2, 3). The status panel on the side shows whose "
            "turn it is.\n\n"
            "IMPORTANT — only pieces with an EMPTY square diagonally forward of "
            "them can move. On the first move, that means only pieces in row 3 "
            "(a3, c3, e3, or g3) — the row-1 and row-2 pieces are blocked by "
            "your own pieces in front of them and CANNOT move yet.\n\n"
            "Make ONE legal move:\n"
            "1. Click a piece in row 3 (a3, c3, e3, or g3). After your click "
            "you should see the square highlighted in yellow.\n"
            "2. Then click the destination square: one row up and one column "
            "left or right (diagonally forward into an empty dark square).\n"
            "3. After the move completes, stop. Do not click further.\n\n"
            "If you click and nothing highlights in yellow, the click missed — "
            "try again. If a square is highlighted yellow, do NOT click it "
            "again; click the destination instead."
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
        # Per-turn enrichment: pull legalMoves from the page's window.checkers
        # API and surface concrete pixel coordinates so Northstar doesn't have
        # to do spatial reasoning. This is the win the game's author left for
        # us — the UI exposes a programmatic state hook.
        pre_turn_js="""
            // Compute legal red-piece moves directly from the DOM. We avoid
            // window.checkers because it's set inside a useEffect that doesn't
            // appear to fire reliably in Kernel's stealth-mode browser.
            const colsToIdx = { a: 0, b: 1, c: 2, d: 3, e: 4, f: 5, g: 6, h: 7 };
            const idxToCol = ['a','b','c','d','e','f','g','h'];
            const center = (sq) => {
              const el = document.querySelector(`[data-square="${sq}"]`);
              if (!el) return null;
              const r = el.getBoundingClientRect();
              return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
            };
            const piece = (sq) => {
              const el = document.querySelector(`[data-square="${sq}"]`);
              return el ? el.getAttribute('data-piece') : null;
            };

            const moves = [];
            for (const col of idxToCol) {
              for (let row = 1; row <= 8; row++) {
                const sq = col + row;
                const p = piece(sq);
                // Only red non-king men move forward (toward row 8).
                if (p !== 'red') continue;
                const ci = colsToIdx[col];
                for (const dc of [-1, 1]) {
                  const nci = ci + dc;
                  const nrow = row + 1;
                  if (nci < 0 || nci > 7 || nrow > 8) continue;
                  const dest = idxToCol[nci] + nrow;
                  if (piece(dest) === 'empty') {
                    moves.push({ from: sq, to: dest, isCapture: false });
                  } else if (piece(dest) === 'black' || piece(dest) === 'black-king') {
                    // Capture: jump over to (col+2dc, row+2)
                    const jci = ci + 2 * dc;
                    const jrow = row + 2;
                    if (jci < 0 || jci > 7 || jrow > 8) continue;
                    const jump = idxToCol[jci] + jrow;
                    if (piece(jump) === 'empty') {
                      moves.push({ from: sq, to: jump, isCapture: true });
                    }
                  }
                }
              }
            }
            if (moves.length === 0) return '';

            const lines = ['LEGAL MOVES — exact pixel coordinates to click:'];
            for (const m of moves.slice(0, 12)) {
              const a = center(m.from), b = center(m.to);
              if (!a || !b) continue;
              const tag = m.isCapture ? ' [CAPTURE]' : '';
              lines.push(`  ${m.from} -> ${m.to}${tag}: click (${a.x}, ${a.y}) then click (${b.x}, ${b.y})`);
            }
            lines.push('');
            lines.push('Pick ONE move from the list. Click the source pixel, wait, then click the destination pixel. After the destination click, stop emitting actions.');
            return lines.join('\\n');
        """,
        max_turn_steps=10,
        poll_interval_s=1.0,
    )
