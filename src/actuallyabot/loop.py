"""Northstar action loop — game-agnostic core.

Drives a Kernel session via Northstar. Returns when:
  - the model emits no computer_call (terminal: typically a 'message' output),
  - the same action repeats STUCK_WINDOW times,
  - max_steps is hit,
  - the optional `should_stop` callback returns True (e.g. opponent's turn began).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Callable

from kernel import Kernel
from tzafon import Lightcone

from .actions import execute, signature


@dataclass
class LoopResult:
    reason: str
    steps: int
    last_response_id: str | None
    final_message: str | None  # extracted text from a terminal 'message' output


def _screenshot_b64(k: Kernel, session_id: str) -> str:
    return base64.b64encode(
        k.browsers.computer.capture_screenshot(session_id).read()
    ).decode()


def _extract_message(response) -> str | None:
    for o in response.output or []:
        if getattr(o, "type", None) == "message":
            parts = []
            for c in getattr(o, "content", []) or []:
                if getattr(c, "type", None) == "output_text":
                    parts.append(c.text)
            return "\n".join(parts) if parts else None
    return None


def run(
    *,
    k: Kernel,
    tz: Lightcone,
    session_id: str,
    instruction: str,
    viewport: tuple[int, int],
    max_steps: int = 25,
    stuck_window: int = 4,
    should_stop: Callable[[], bool] | None = None,
    inter_step_pause_s: float = 0.6,
    model: str = "tzafon.northstar-cua-fast",
    on_step: Callable[[int, object], None] | None = None,
) -> LoopResult:
    tool = {
        "type": "computer_use",
        "display_width": viewport[0],
        "display_height": viewport[1],
        "environment": "browser",
    }

    img = _screenshot_b64(k, session_id)
    response = tz.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": instruction},
                {"type": "input_image", "image_url": f"data:image/png;base64,{img}", "detail": "auto"},
            ],
        }],
        tools=[tool],
    )

    history: list[tuple] = []
    last_id = response.id

    for step in range(max_steps):
        last_id = response.id
        if should_stop and should_stop():
            return LoopResult("stop_signal", step, last_id, None)

        call = next(
            (o for o in (response.output or []) if getattr(o, "type", None) == "computer_call"),
            None,
        )
        if call is None:
            return LoopResult("no_computer_call", step, last_id, _extract_message(response))

        action = call.action
        if on_step:
            on_step(step, action)

        sig = signature(action)
        history.append(sig)
        if len(history) >= stuck_window and len(set(history[-stuck_window:])) == 1:
            return LoopResult("stuck", step, last_id, None)

        execute(k, session_id, action, viewport=viewport)

        import time
        time.sleep(inter_step_pause_s)

        img = _screenshot_b64(k, session_id)
        response = tz.responses.create(
            model=model,
            previous_response_id=response.id,
            input=[{
                "type": "computer_call_output",
                "call_id": call.call_id,
                "output": {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{img}",
                    "detail": "auto",
                },
            }],
            tools=[tool],
        )

    return LoopResult("max_steps", max_steps, last_id, None)
