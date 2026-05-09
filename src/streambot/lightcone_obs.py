from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from tzafon import AuthenticationError, Lightcone, LightconeError, RateLimitError

from .controller import DEFAULT_YOUTUBE_RTMP_URL


@dataclass(frozen=True)
class Source:
    name: str
    url: str


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _split_sources(raw: str) -> list[Source]:
    sources: list[Source] = []
    for i, item in enumerate(part.strip() for part in raw.split(",") if part.strip()):
        if "=" in item:
            name, url = item.split("=", 1)
            sources.append(Source(name=name.strip() or f"Source {i + 1}", url=url.strip()))
        else:
            sources.append(Source(name=f"Source {i + 1}", url=item))
    return sources


def _sources_from_args(values: list[str], env_raw: str | None) -> list[Source]:
    sources: list[Source] = []
    if env_raw:
        sources.extend(_split_sources(env_raw))
    for i, value in enumerate(values, start=len(sources) + 1):
        if "=" in value:
            name, url = value.split("=", 1)
            sources.append(Source(name=name.strip() or f"Source {i}", url=url.strip()))
        else:
            sources.append(Source(name=f"Source {i}", url=value.strip()))
    return [source for source in sources if source.url]


def _task_stream_timeout() -> httpx.Timeout:
    raw = os.environ.get("LIGHTCONE_TASK_STREAM_TIMEOUT_SEC", "").strip()
    read_sec = float(raw) if raw else 14_400.0
    return httpx.Timeout(connect=120.0, read=read_sec, write=120.0, pool=120.0)


def _print_latest_desktop(client: Lightcone) -> None:
    try:
        computers = client.computers.list(type="live")
    except Exception as exc:
        print(f"[streambot] could not list Lightcone computers: {exc}", file=sys.stderr)
        return
    desktops = [c for c in computers if getattr(c, "kind", None) == "desktop"]
    if not desktops:
        return
    chosen = sorted(
        desktops,
        key=lambda c: (getattr(c, "last_activity_at", "") or "", getattr(c, "created_at", "") or ""),
        reverse=True,
    )[0]
    print(f"[streambot] latest desktop computer_id={getattr(chosen, 'id', '')}", flush=True)
    endpoints = getattr(chosen, "endpoints", None) or {}
    for name, url in endpoints.items():
        print(f"[streambot] endpoint {name}={url}", flush=True)


def build_instruction(
    *,
    stream_key: str,
    rtmp_server_url: str,
    sources: list[Source],
    start_scene: str,
) -> str:
    source_lines = "\n".join(
        f"- {source.name}: {source.url}" for source in sources
    ) or "- Waiting Room: https://example.com"
    source_json = json.dumps([source.__dict__ for source in sources], indent=2)
    return f"""
You are operating a Linux desktop in Lightcone. Set up OBS Studio inside this Lightcone VM and stream to YouTube RTMP.

Hard requirements:
- Use shell commands and OBS configuration files wherever possible.
- Install OBS Studio and Firefox if missing.
- Configure OBS in this VM, not on the user's local machine.
- Stream to this RTMP server exactly: {rtmp_server_url}
- Use this YouTube stream key exactly, keeping it out of visible logs where practical: {stream_key}
- Add these incoming streams as OBS Browser Sources:
{source_lines}
- Create one full-canvas OBS scene per source, named exactly after the source name.
- Set the initial/current scene to: {start_scene}
- Start streaming from OBS and verify OBS reports an active stream attempt.

Implementation guidance:
1. Install dependencies:
   apt-get update && apt-get install -y obs-studio firefox python3
2. Launch OBS once to materialize config, then stop it cleanly if needed.
3. Prefer writing OBS profile/scene JSON files under ~/.config/obs-studio/basic.
4. Use a YouTube/custom RTMP service config with type rtmp_custom, server {rtmp_server_url}, and the given key.
5. For browser sources, use OBS Browser Source inputs. Set each source to 1280x720 or the OBS canvas size, fill the scene, and use the URL exactly.
6. If file-based scene creation is unreliable on this OBS build, use the OBS UI only for source creation and scene switching.
7. Start OBS with --startstreaming after the profile and scene collection are configured, or start the stream through the OBS UI if CLI start fails.

Structured source list for scripts:
{source_json}

When finished, leave OBS running and streaming. In your final status, report:
- the scene names created
- which scene is currently live
- whether OBS shows streaming active
- any Lightcone/computer/session identifier visible to you
"""


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Run OBS inside a Lightcone desktop task and stream sources to YouTube."
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Browser source as URL or Name=URL. Repeat for multiple sources.",
    )
    parser.add_argument(
        "--sources",
        default=os.environ.get("STREAMBOT_SOURCE_URLS"),
        help="Comma-separated URL or Name=URL values. Defaults to STREAMBOT_SOURCE_URLS.",
    )
    parser.add_argument("--start-scene", default=os.environ.get("STREAMBOT_START_SCENE", "Observer"))
    parser.add_argument("--stream-key", default=os.environ.get("STREAM_KEY"))
    parser.add_argument("--rtmp-server-url", default=os.environ.get("RTMP_SERVER_URL", DEFAULT_YOUTUBE_RTMP_URL))
    parser.add_argument("--max-steps", type=int, default=int(os.environ.get("LIGHTCONE_TASK_MAX_STEPS", "180")))
    parser.add_argument("--model", default=os.environ.get("LIGHTCONE_TASK_MODEL", "tzafon.northstar-cua-fast"))
    parser.add_argument("--width", type=int, default=int(os.environ.get("LIGHTCONE_VIEWPORT_WIDTH", "1280")))
    parser.add_argument("--height", type=int, default=int(os.environ.get("LIGHTCONE_VIEWPORT_HEIGHT", "720")))
    args = parser.parse_args()

    _require_env("TZAFON_API_KEY")
    stream_key = args.stream_key.strip() if args.stream_key else ""
    if not stream_key:
        print("Missing --stream-key or STREAM_KEY", file=sys.stderr)
        sys.exit(1)

    sources = _sources_from_args(args.source, args.sources)
    if not sources:
        print("Missing --source or STREAMBOT_SOURCE_URLS", file=sys.stderr)
        sys.exit(1)

    instruction = build_instruction(
        stream_key=stream_key,
        rtmp_server_url=args.rtmp_server_url,
        sources=sources,
        start_scene=args.start_scene,
    )

    client = Lightcone()
    print("[streambot] starting Lightcone desktop OBS task", flush=True)
    _print_latest_desktop(client)
    try:
        for event in client.agent.tasks.start_stream(
            instruction=instruction.strip(),
            kind="desktop",
            model=args.model,
            max_steps=args.max_steps,
            viewport_width=args.width,
            viewport_height=args.height,
            timeout=_task_stream_timeout(),
        ):
            print(event, flush=True)
    except httpx.ReadTimeout:
        print("Timed out waiting for Lightcone task events.", file=sys.stderr)
        sys.exit(5)
    except AuthenticationError:
        print("Authentication failed - check TZAFON_API_KEY", file=sys.stderr)
        sys.exit(2)
    except RateLimitError:
        print("Rate limited by Lightcone.", file=sys.stderr)
        sys.exit(3)
    except LightconeError as exc:
        print(f"Lightcone API error: {exc}", file=sys.stderr)
        sys.exit(4)
    finally:
        _print_latest_desktop(client)


if __name__ == "__main__":
    main()
