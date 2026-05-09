"""Per-turn orchestration loop. Game-agnostic.

while not game_over:
  if our_turn:    run northstar for one move (bounded)
  else:           poll until our turn

After each Northstar turn, we extract optional state via the adapter and emit
an event to the streamer.
"""
from __future__ import annotations

import time

from kernel import Kernel
from tzafon import Lightcone

from . import dom, loop
from .events import EventPublisher
from .games.base import Game


def play(
    *,
    k: Kernel,
    tz: Lightcone,
    session_id: str,
    game: Game,
    viewport: tuple[int, int],
    publisher: EventPublisher,
    max_total_turns: int = 200,
) -> None:
    if game.max_turns is not None:
        max_total_turns = min(max_total_turns, game.max_turns)
    if game.preflight_js:
        try:
            dom.evaluate(k, session_id, game.preflight_js)
        except Exception as e:
            print(f"[orchestrator] preflight failed (continuing): {e}")

    turn = 0
    while turn < max_total_turns:
        # Game over?
        if game.game_over_js and dom.predicate(k, session_id, game.game_over_js):
            publisher.emit_sync("game_over", {"turn": turn})
            print(f"[orchestrator] game over at turn {turn}")
            return

        # Our turn?
        if game.is_our_turn_js and not dom.predicate(k, session_id, game.is_our_turn_js):
            time.sleep(game.poll_interval_s)
            continue

        # Take one Northstar turn.
        publisher.emit_sync("turn_start", {"turn": turn})

        def on_step(step_idx: int, action) -> None:
            print(f"  [turn {turn} step {step_idx}] {action.type} {action.model_dump(mode='json')}")

        result = loop.run(
            k=k, tz=tz, session_id=session_id,
            instruction=game.instruction,
            viewport=viewport,
            max_steps=game.max_turn_steps,
            should_stop=(
                (lambda: not dom.predicate(k, session_id, game.is_our_turn_js))
                if game.is_our_turn_js else None
            ),
            on_step=on_step,
        )
        print(f"[turn {turn}] done reason={result.reason} steps={result.steps}")

        # Optional state snapshot for events.
        state = None
        if game.state_extractor_js:
            try:
                state = dom.evaluate(k, session_id, game.state_extractor_js)
            except Exception as e:
                print(f"[orchestrator] state extract failed: {e}")

        publisher.emit_sync(
            "turn_end",
            {
                "turn": turn,
                "reason": result.reason,
                "steps": result.steps,
                "final_message": result.final_message,
                "state": state,
            },
        )

        turn += 1
        time.sleep(game.poll_interval_s)

    print(f"[orchestrator] hit max_total_turns={max_total_turns}")
