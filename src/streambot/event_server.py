from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .controller import StreamController, StreamLayout
from .obsws import ObsClient


def make_handler(controller: StreamController) -> type[BaseHTTPRequestHandler]:
    class EventHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/events":
                self._send_json(404, {"error": "not_found"})
                return
            length = int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(length)
            try:
                event = json.loads(raw.decode("utf-8"))
                scene = controller.handle_event(event)
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return
            self._send_json(200, {"ok": True, "scene": scene})

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[streambot] {self.address_string()} {fmt % args}")

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return EventHandler


def serve(host: str, port: int, controller_factory: Callable[[], StreamController]) -> None:
    controller = controller_factory()
    server = ThreadingHTTPServer((host, port), make_handler(controller))
    print(f"[streambot] listening on http://{host}:{port}/events")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="OBS scene switch event endpoint for actuallyabot.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    def factory() -> StreamController:
        obs = ObsClient()
        obs.connect()
        return StreamController(obs, StreamLayout.from_env())

    serve(args.host, args.port, factory)


if __name__ == "__main__":
    main()

