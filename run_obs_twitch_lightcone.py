#!/usr/bin/env python3
"""
Drive a Lightcone cloud desktop via the Tasks API to install OBS,
configure full-desktop capture (prefer config files + OBS CLI flags), skim
YouTube Live + OBS setup notes in Firefox, apply RTMP settings via profile
JSON (not the OBS Stream settings GUI when avoidable), then start streaming
with --startstreaming.

Requires:
  - TZAFON_API_KEY (Lightcone / Tzafon API key)
  - STREAM_KEY (YouTube stream key; never commit it)

Optional:
  - RTMP_SERVER_URL — ingest URL (default rtmp://a.rtmp.youtube.com/live2)
  - LIGHTCONE_TASK_STREAM_TIMEOUT_SEC — max seconds between SSE chunks while
    streaming task events (default 14400). The tzafon client defaults to ~60s,
    which trips httpx.ReadTimeout on long-running desktop tasks.

Do not commit stream keys. Rotate any key that has been pasted into chat or logs.
"""

from __future__ import annotations

import os
import sys

import httpx

from tzafon import AuthenticationError, Lightcone, LightconeError, RateLimitError


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return value


DEFAULT_YOUTUBE_RTMP_URL = "rtmp://a.rtmp.youtube.com/live2"


def build_instruction(rtmp_server_url: str, stream_key: str) -> str:
    # Placeholders avoid f-strings (keys may contain "{" / "}") and keep logic obvious.
    key_tok = "<<<STREAM_KEY>>>"
    url_tok = "<<<RTMP_SERVER_URL>>>"
    template = """
Complete the following on this Linux desktop. Stream full-desktop capture to YouTube via RTMP using the server URL and stream key given below (do not confuse “stream key” with the watch URL).

CLI-FIRST RULE: Prefer shell commands and OBS launch flags over clicking through OBS. Use the OBS UI only when there is no documented CLI or on-disk config equivalent (after reading `obs --help`). Avoid echoing the stream key into the shell as plaintext arguments where avoidable—embed it with `python3` + `json.dumps` when writing JSON.

Target RTMP ingest (server URL string used verbatim as OBS “Server” / `server` field):
<<<RTMP_SERVER_URL>>>

1) Install (CLI):
   apt-get update && apt-get install -y obs-studio firefox

2) OBS automation surface (CLI discovery):
   Run `obs --help` (and `obs --version`). Plan to use `--profile`, `--collection`, `--scene`, `--startstreaming`, and `--verbose` per https://obsproject.com/kb/launch-parameters

3) Materialize default profile/scene files without relying on the setup wizard when possible:
   - Launch once briefly so OBS creates `~/.config/obs-studio/basic/profiles` and `basic/scenes`, e.g. `timeout 25 obs --verbose &` then wait, then stop OBS (`pkill -x obs` or quit cleanly).
   - If a first-run wizard blocks unattended runs, dismiss it with minimal interaction only after checking for non-interactive alternatives.

4) Stream output BY FILE (not OBS Settings → Stream UI):
   - Pick the profile directory you will pass to `--profile` (create/rename folders under `basic/profiles` via `mv`/`mkdir` so the folder name matches the flag).
   - Overwrite that profile's `service.json` using `python3` + `json.dumps` so specials in the key are escaped. Use `"type": "rtmp_custom"` with:
     - `"server"` exactly: <<<RTMP_SERVER_URL>>>
     - `"key"` exactly this YouTube stream key (no quotes/spaces around it — confidential):
       <<<STREAM_KEY>>>
     - `"use_auth": false` when appropriate for `rtmp_custom` on this OBS build.

5) Desktop capture:
   - Prefer editing the active scene collection JSON under `basic/scenes/` so a full-monitor/display capture source fills the canvas (inspect OBS-generated JSON from step 3 for the correct Linux capture source kind/settings).
   - If file-based editing fails, add Display/Monitor/Desktop Capture once via OBS UI—this is the only intended GUI-heavy step.

6) Firefox (required research step): open Firefox from the shell (`firefox … &`). Search for YouTube Help or Creator docs on streaming with OBS (encoder setup, stream URL vs stream key). Skim a credible result so the step is visibly done.

7) Start streaming via OBS CLI (primary path):
   `obs --profile "<ProfileName>" --collection "<SceneCollectionName>" --scene "<SceneName>" --startstreaming --verbose &`
   Match names to folders/files under `basic/profiles` and `basic/scenes`. Raise the OBS window if visibility is required.

8) If streaming fails, fix `service.json` (server/key typos, trailing slashes) and relaunch with the same flags; avoid the OBS settings UI for secrets unless disk edits fail.

Declare done only when OBS reports an active/live encode/stream attempt for full-desktop capture with server <<<RTMP_SERVER_URL>>> and stream key <<<STREAM_KEY>>> persisted under the profile (`service.json` or equivalent on-disk config), not typed only into transient UI fields without saving.
"""
    if template.count(key_tok) != 2:
        raise RuntimeError("instruction template must mention stream key token exactly twice")
    if template.count(url_tok) != 3:
        raise RuntimeError("instruction template must mention RTMP URL token exactly three times")
    return template.replace(url_tok, rtmp_server_url).replace(key_tok, stream_key)


def _task_stream_timeout() -> httpx.Timeout:
    """SSE reads can stall longer than the SDK default (60s between chunks)."""
    raw = os.environ.get("LIGHTCONE_TASK_STREAM_TIMEOUT_SEC", "").strip()
    read_sec = float(raw) if raw else 14_400.0  # 4 hours between chunks
    return httpx.Timeout(connect=120.0, read=read_sec, write=120.0, pool=120.0)


def main() -> None:
    _require_env("TZAFON_API_KEY")
    stream_key = _require_env("STREAM_KEY")
    rtmp_url = os.environ.get("RTMP_SERVER_URL", "").strip() or DEFAULT_YOUTUBE_RTMP_URL
    instruction = build_instruction(rtmp_url, stream_key)

    client = Lightcone()

    max_steps = int(os.environ.get("LIGHTCONE_TASK_MAX_STEPS", "140"))
    model = os.environ.get("LIGHTCONE_TASK_MODEL", "tzafon.northstar-cua-fast")
    viewport_w = os.environ.get("LIGHTCONE_VIEWPORT_WIDTH")
    viewport_h = os.environ.get("LIGHTCONE_VIEWPORT_HEIGHT")
    kwargs = dict(
        instruction=instruction.strip(),
        kind="desktop",
        model=model,
        max_steps=max_steps,
    )
    if viewport_w and viewport_h:
        kwargs["viewport_width"] = int(viewport_w)
        kwargs["viewport_height"] = int(viewport_h)

    kwargs["timeout"] = _task_stream_timeout()

    print("Starting Lightcone task stream (northstar)...", flush=True)
    try:
        for event in client.agent.tasks.start_stream(**kwargs):
            print(event, flush=True)
    except httpx.ReadTimeout:
        print(
            "HTTP read timed out waiting for the next task stream event. "
            "Increase LIGHTCONE_TASK_STREAM_TIMEOUT_SEC (seconds between SSE chunks).",
            file=sys.stderr,
        )
        sys.exit(5)
    except AuthenticationError:
        print("Authentication failed — check TZAFON_API_KEY", file=sys.stderr)
        sys.exit(2)
    except RateLimitError:
        print("Rate limited — retry later / reduce parallelism", file=sys.stderr)
        sys.exit(3)
    except LightconeError as exc:
        print(f"Lightcone API error: {exc}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
