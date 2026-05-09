"""Kernel browser session — thin wrapper exposing what the player and streamer need."""
from __future__ import annotations

from dataclasses import dataclass

from kernel import Kernel


@dataclass
class Session:
    session_id: str
    cdp_ws_url: str
    browser_live_view_url: str
    _kernel: Kernel

    def close(self) -> None:
        self._kernel.browsers.delete_by_id(self.session_id)


def open_session(
    *,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    timeout_seconds: int = 1800,
    stealth: bool = True,
    kiosk_mode: bool = True,
    profile_id: str | None = None,
) -> Session:
    k = Kernel()
    kwargs: dict = {
        "stealth": stealth,
        "headless": False,
        "kiosk_mode": kiosk_mode,
        "viewport": {"width": viewport_width, "height": viewport_height},
        "timeout_seconds": timeout_seconds,
    }
    if profile_id:
        kwargs["profile"] = {"id": profile_id, "save_changes": True}
    b = k.browsers.create(**kwargs)
    return Session(
        session_id=b.session_id,
        cdp_ws_url=b.cdp_ws_url,
        browser_live_view_url=b.browser_live_view_url,
        _kernel=k,
    )
