"""Game-state event publisher.

Streamer agent (separate repo) consumes these. Schema:
  {type, ts, session_id, payload}

If STREAMER_EVENT_ENDPOINT is unset, events are stdout-only — useful for dev.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx


class EventPublisher:
    def __init__(self, session_id: str, endpoint: str | None = None) -> None:
        self.session_id = session_id
        self.endpoint = endpoint or os.environ.get("STREAMER_EVENT_ENDPOINT") or None
        self._client: httpx.Client | None = httpx.Client(timeout=2.0) if self.endpoint else None

    def emit_sync(self, type_: str, payload: dict[str, Any]) -> None:
        event = {
            "type": type_,
            "ts": time.time(),
            "session_id": self.session_id,
            "payload": payload,
        }
        print(f"[event] {json.dumps(event, default=str)}")
        if self._client and self.endpoint:
            try:
                self._client.post(self.endpoint, json=event)
            except httpx.HTTPError as e:
                print(f"[event] publish failed (best-effort): {e}")

    def close(self) -> None:
        if self._client:
            self._client.close()
