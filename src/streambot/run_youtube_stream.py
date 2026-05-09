from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from .controller import DEFAULT_YOUTUBE_RTMP_URL, StreamController, StreamLayout
from .obsws import ObsClient, ObsError


def _require(value: str | None, label: str) -> str:
    if value and value.strip():
        return value.strip()
    print(f"Missing required {label}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Configure OBS scenes and start YouTube streaming via OBS WebSocket."
    )
    parser.add_argument("--player-live-view-url", default=os.environ.get("PLAYER_LIVE_VIEW_URL"))
    parser.add_argument("--opponent-live-view-url", default=os.environ.get("OPPONENT_LIVE_VIEW_URL"))
    parser.add_argument("--observer-url", default=os.environ.get("OBSERVER_URL"))
    parser.add_argument("--stream-key", default=os.environ.get("STREAM_KEY"))
    parser.add_argument("--rtmp-server-url", default=os.environ.get("RTMP_SERVER_URL", DEFAULT_YOUTUBE_RTMP_URL))
    parser.add_argument("--no-start", action="store_true", help="Configure OBS but do not start streaming.")
    args = parser.parse_args()

    player_url = _require(args.player_live_view_url, "--player-live-view-url or PLAYER_LIVE_VIEW_URL")

    try:
        with ObsClient() as obs:
            controller = StreamController(obs, StreamLayout.from_env())
            controller.ensure_layout(
                player_live_view_url=player_url,
                opponent_live_view_url=args.opponent_live_view_url,
                observer_url=args.observer_url,
            )
            if not args.no_start:
                stream_key = _require(args.stream_key, "--stream-key or STREAM_KEY")
                controller.configure_stream_service(stream_key, args.rtmp_server_url)
                controller.start_streaming()
            print("[streambot] OBS configured")
            print("[streambot] event endpoint command: python -m streambot.event_server --host 127.0.0.1 --port 8765")
    except ObsError as exc:
        print(f"OBS error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

