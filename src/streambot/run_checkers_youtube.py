from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

from dotenv import load_dotenv

from .controller import DEFAULT_YOUTUBE_RTMP_URL, StreamController, StreamLayout
from .event_server import make_handler
from .obsws import ObsClient, ObsError


LIVE_VIEW_RE = re.compile(r"\[session\]\s+live_view_url=(\S+)")


def _require(value: str | None, label: str) -> str:
    if value and value.strip():
        return value.strip()
    print(f"Missing required {label}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run the checkers CUA and stream its Kernel live view to YouTube via OBS."
    )
    parser.add_argument("--game", default=os.environ.get("GAME", "checkers_custom"))
    parser.add_argument("--url", default=os.environ.get("GAME_URL_OVERRIDE") or None)
    parser.add_argument("--width", type=int, default=int(os.environ.get("PLAYER_WIDTH", "1280")))
    parser.add_argument("--height", type=int, default=int(os.environ.get("PLAYER_HEIGHT", "800")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("PLAYER_TIMEOUT", "1800")))
    parser.add_argument("--profile", default=os.environ.get("KERNEL_PROFILE") or None)
    parser.add_argument("--event-host", default=os.environ.get("STREAMBOT_EVENT_HOST", "127.0.0.1"))
    parser.add_argument("--event-port", type=int, default=int(os.environ.get("STREAMBOT_EVENT_PORT", "8765")))
    parser.add_argument("--stream-key", default=os.environ.get("STREAM_KEY"))
    parser.add_argument("--rtmp-server-url", default=os.environ.get("RTMP_SERVER_URL", DEFAULT_YOUTUBE_RTMP_URL))
    parser.add_argument("--no-start", action="store_true", help="Configure OBS but do not start streaming.")
    args = parser.parse_args()

    obs = ObsClient()
    try:
        obs.connect()
    except ObsError as exc:
        print(f"OBS error: {exc}", file=sys.stderr)
        sys.exit(2)

    controller = StreamController(obs, StreamLayout.from_env())
    server = ThreadingHTTPServer((args.event_host, args.event_port), make_handler(controller))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://{args.event_host}:{args.event_port}/events"
    print(f"[streambot] event endpoint {endpoint}")

    env = os.environ.copy()
    env["STREAMER_EVENT_ENDPOINT"] = endpoint
    cmd = [
        sys.executable,
        "-m",
        "actuallyabot.main",
        "--game",
        args.game,
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--timeout",
        str(args.timeout),
    ]
    if args.url:
        cmd.extend(["--url", args.url])
    if args.profile:
        cmd.extend(["--profile", args.profile])

    print(f"[streambot] launching player: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    configured = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            if configured:
                continue
            match = LIVE_VIEW_RE.search(line)
            if not match:
                continue
            live_view_url = match.group(1)
            controller.ensure_layout(player_live_view_url=live_view_url)
            if not args.no_start:
                stream_key = _require(args.stream_key, "--stream-key or STREAM_KEY")
                controller.configure_stream_service(stream_key, args.rtmp_server_url)
                controller.start_streaming()
            configured = True
            print("[streambot] OBS is configured for the player live view")
        rc = proc.wait()
        if rc != 0:
            sys.exit(rc)
    finally:
        server.shutdown()
        obs.close()


if __name__ == "__main__":
    main()

