from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from websocket import create_connection


class ObsError(RuntimeError):
    pass


@dataclass(frozen=True)
class ObsConfig:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    timeout_s: float = 5.0

    @classmethod
    def from_env(cls) -> "ObsConfig":
        return cls(
            host=os.environ.get("OBS_WS_HOST", "127.0.0.1"),
            port=int(os.environ.get("OBS_WS_PORT", "4455")),
            password=os.environ.get("OBS_WS_PASSWORD", ""),
            timeout_s=float(os.environ.get("OBS_WS_TIMEOUT_SEC", "5")),
        )


class ObsClient:
    """Tiny OBS WebSocket v5 client.

    This keeps stream startup scriptable without requiring humans or the CUA to
    drive OBS Settings dialogs. It intentionally implements only the request
    path we need for scene/source setup and stream control.
    """

    def __init__(self, config: ObsConfig | None = None) -> None:
        self.config = config or ObsConfig.from_env()
        self._ws = None

    def __enter__(self) -> "ObsClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        url = f"ws://{self.config.host}:{self.config.port}"
        self._ws = create_connection(url, timeout=self.config.timeout_s)
        hello = self._recv()
        if hello.get("op") != 0:
            raise ObsError(f"Expected Hello from OBS, got {hello!r}")

        auth = self._auth_payload(hello.get("d", {}))
        self._send({"op": 1, "d": {"rpcVersion": 1, **auth}})
        identified = self._recv()
        if identified.get("op") != 2:
            raise ObsError(f"OBS identify failed: {identified!r}")

    def close(self) -> None:
        if self._ws:
            self._ws.close()
            self._ws = None

    def call(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = secrets.token_hex(8)
        self._send(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": data or {},
                },
            }
        )
        deadline = time.time() + self.config.timeout_s
        while time.time() < deadline:
            msg = self._recv()
            if msg.get("op") != 7:
                continue
            payload = msg.get("d", {})
            if payload.get("requestId") != request_id:
                continue
            status = payload.get("requestStatus", {})
            if not status.get("result"):
                code = status.get("code")
                comment = status.get("comment") or "OBS request failed"
                raise ObsError(f"{request_type} failed ({code}): {comment}")
            return payload.get("responseData") or {}
        raise ObsError(f"Timed out waiting for OBS response to {request_type}")

    def try_call(self, request_type: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            return self.call(request_type, data)
        except ObsError:
            return None

    def _auth_payload(self, hello_data: dict[str, Any]) -> dict[str, str]:
        auth = hello_data.get("authentication")
        if not auth:
            return {}
        if not self.config.password:
            raise ObsError("OBS WebSocket requires OBS_WS_PASSWORD")
        salt = auth["salt"]
        challenge = auth["challenge"]
        secret = base64.b64encode(
            hashlib.sha256((self.config.password + salt).encode()).digest()
        ).decode()
        response = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
        return {"authentication": response}

    def _send(self, payload: dict[str, Any]) -> None:
        if not self._ws:
            raise ObsError("OBS client is not connected")
        self._ws.send(json.dumps(payload))

    def _recv(self) -> dict[str, Any]:
        if not self._ws:
            raise ObsError("OBS client is not connected")
        return json.loads(self._ws.recv())

