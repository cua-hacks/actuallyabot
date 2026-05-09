"""Northstar action → Kernel computer-control dispatch.

Action shapes verified against tzafon SDK source (.venv/.../tzafon/types/action_*.py):
  click(button, x, y), double_click(x,y), drag(path:[{x,y}]), keypress(keys),
  move(x,y), scroll(x,y,scroll_x,scroll_y), type(text), wait, screenshot.

Coordinate clamping is required — Northstar can emit out-of-bounds values.
"""
from __future__ import annotations

import time
from typing import Any

from kernel import Kernel


def _clamp(v: int | None, lo: int, hi: int, default: int) -> int:
    if v is None:
        return default
    return max(lo, min(int(v), hi))


def execute(
    k: Kernel, session_id: str, action: Any, *, viewport: tuple[int, int]
) -> None:
    """Apply one Northstar action via Kernel's computer-control API.

    Unknown action types are skipped with a print, not raised — Northstar may
    occasionally emit primitives we don't model (mouse_down/up, key_down/up).
    """
    d = action.model_dump(mode="json")
    t = d["type"]
    vw, vh = viewport
    xmax, ymax = vw - 1, vh - 1

    if t == "click":
        k.browsers.computer.click_mouse(
            session_id,
            x=_clamp(d.get("x"), 0, xmax, vw // 2),
            y=_clamp(d.get("y"), 0, ymax, vh // 2),
            button=d.get("button") or "left",
        )
    elif t == "double_click":
        k.browsers.computer.click_mouse(
            session_id,
            x=_clamp(d.get("x"), 0, xmax, vw // 2),
            y=_clamp(d.get("y"), 0, ymax, vh // 2),
            num_clicks=2,
        )
    elif t == "move":
        k.browsers.computer.move_mouse(
            session_id,
            x=_clamp(d.get("x"), 0, xmax, vw // 2),
            y=_clamp(d.get("y"), 0, ymax, vh // 2),
        )
    elif t == "type":
        k.browsers.computer.type_text(session_id, text=d["text"])
    elif t == "keypress":
        k.browsers.computer.press_key(session_id, keys=d["keys"])
    elif t == "scroll":
        k.browsers.computer.scroll(
            session_id,
            x=_clamp(d.get("x"), 0, xmax, vw // 2),
            y=_clamp(d.get("y"), 0, ymax, vh // 2),
            delta_x=d.get("scroll_x") or 0,
            delta_y=d.get("scroll_y") or 0,
        )
    elif t == "drag":
        path = [
            [_clamp(p["x"], 0, xmax, vw // 2), _clamp(p["y"], 0, ymax, vh // 2)]
            for p in d.get("path") or []
        ]
        if len(path) >= 2:
            k.browsers.computer.drag_mouse(session_id, path=path)
    elif t == "wait":
        time.sleep(1.0)
    elif t == "screenshot":
        # Model asked to see the screen; the next loop iteration sends a fresh shot.
        pass
    else:
        print(f"[actions] unhandled type={t} dump={d}")


def signature(action: Any) -> tuple:
    """Coarse identity used for stuck detection. Same type+coords ⇒ same action."""
    d = action.model_dump(mode="json")
    t = d.get("type")
    if t in ("click", "double_click", "move"):
        return (t, d.get("x"), d.get("y"), d.get("button"))
    if t == "type":
        return (t, d.get("text"))
    if t == "keypress":
        return (t, tuple(d.get("keys") or []))
    if t == "drag":
        path = d.get("path") or []
        return (t, tuple((p["x"], p["y"]) for p in path))
    if t == "scroll":
        return (t, d.get("scroll_x"), d.get("scroll_y"))
    return (t,)
