#!/usr/bin/env python3
"""
Stream video/cursor traffic from an active Lightcone computer session via GET
/computers/{id}/screencast (SSE). Session shapes match the API docs:
https://docs.lightcone.ai/api/resources/computers/methods/retrieve_screencast

Requires:
  - TZAFON_API_KEY

Optional:
  - LIGHTCONE_BASE_URL — API base (default https://api.tzafon.ai)
  - LIGHTCONE_SCREENCAST_READ_TIMEOUT_SEC — max seconds between SSE chunks while
    idle (default 120). Heartbeats arrive every ~30s.

Selection:
  - Pass --computer-id to pin a session.
  - Omit it to use the latest active session (by last_activity_at, then created_at).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone
from typing import BinaryIO, Iterator

import httpx

from tzafon import AuthenticationError, Lightcone, LightconeError, RateLimitError


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _parse_ts(raw: str | None) -> datetime:
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _sort_key_session(c: object) -> datetime:
    la = getattr(c, "last_activity_at", None)
    cr = getattr(c, "created_at", None)
    t_la = _parse_ts(la if isinstance(la, str) else None)
    t_cr = _parse_ts(cr if isinstance(cr, str) else None)
    return max(t_la, t_cr)


def resolve_computer_id(client: Lightcone, explicit: str | None, session_type: str | None) -> str:
    if explicit:
        return explicit.strip()
    kwargs = {}
    if session_type:
        kwargs["type"] = session_type  # type: ignore[arg-type]
    sessions = client.computers.list(**kwargs)
    if not sessions:
        print("No computer sessions returned from GET /computers", file=sys.stderr)
        sys.exit(6)
    ranked = sorted(sessions, key=_sort_key_session, reverse=True)
    chosen = ranked[0]
    cid = getattr(chosen, "id", None)
    if not cid:
        print("Latest session has no id — API schema mismatch", file=sys.stderr)
        sys.exit(6)
    print(
        f"Using latest session {cid} (kind={getattr(chosen, 'kind', None)!r}, "
        f"status={getattr(chosen, 'status', None)!r})",
        file=sys.stderr,
    )
    return cid


def list_sessions(client: Lightcone, session_type: str | None) -> None:
    kwargs = {}
    if session_type:
        kwargs["type"] = session_type  # type: ignore[arg-type]
    sessions = client.computers.list(**kwargs)
    if not sessions:
        print("(empty)")
        return
    rows = sorted(sessions, key=_sort_key_session, reverse=True)
    for c in rows:
        print(
            f"{getattr(c, 'id', '')}\t"
            f"kind={getattr(c, 'kind', '')}\t"
            f"status={getattr(c, 'status', '')}\t"
            f"last_activity_at={getattr(c, 'last_activity_at', '')}\t"
            f"created_at={getattr(c, 'created_at', '')}"
        )


def _screencast_timeout() -> httpx.Timeout:
    raw = os.environ.get("LIGHTCONE_SCREENCAST_READ_TIMEOUT_SEC", "").strip()
    read_sec = float(raw) if raw else 120.0
    return httpx.Timeout(connect=120.0, read=read_sec, write=120.0, pool=120.0)


def iter_sse_events(lines: Iterator[str]) -> Iterator[tuple[str | None, str]]:
    """Yield (event_name_or_none, data) for each SSE event block."""
    event: str | None = None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith(":"):
            continue
        if line.strip() == "":
            if data_lines:
                yield event, "\n".join(data_lines)
            event = None
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line[6:].strip() or None
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield event, "\n".join(data_lines)


def run_raw_sse(resp: httpx.Response) -> None:
    out = sys.stdout
    for chunk in resp.iter_text():
        out.write(chunk)
        out.flush()


def handle_payload_log(target, event: str | None, data: str) -> None:
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        print(f"sse event={event!r} non-json data ({len(data)} chars)", file=target, flush=True)
        return
    if event == "h264":
        raw_b64 = payload.get("nalu_data")
        if isinstance(raw_b64, str):
            n = len(base64.b64decode(raw_b64, validate=False))
            print(f"h264 nalu bytes={n}", file=target, flush=True)
        else:
            print(f"h264 payload keys={list(payload.keys())}", file=target, flush=True)
        return
    if event == "cursor_update":
        print("cursor_update", file=target, flush=True)
        return
    if event == "cursor_position":
        x, y = payload.get("x"), payload.get("y")
        print(f"cursor_position x={x} y={y}", file=target, flush=True)
        return
    img = payload.get("image_data")
    if isinstance(img, str):
        n = len(base64.b64decode(img, validate=False))
        meta = payload.get("metadata")
        print(f"browser jpeg bytes={n} metadata={meta!r}", file=target, flush=True)
        return
    print(f"event={event!r} keys={list(payload.keys())}", file=target, flush=True)


def handle_payload_pipe(buf: BinaryIO, event: str | None, data: str, *, fmt: str) -> None:
    payload = json.loads(data)
    if fmt == "h264":
        if event != "h264":
            return
        raw_b64 = payload["nalu_data"]
        assert isinstance(raw_b64, str)
        buf.write(base64.b64decode(raw_b64, validate=False))
        buf.flush()
        return
    if fmt == "jpeg":
        if event in ("h264", "cursor_update", "cursor_position"):
            return
        img = payload.get("image_data")
        if not isinstance(img, str):
            return
        buf.write(base64.b64decode(img, validate=False))
        buf.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream Lightcone /computers/{id}/screencast (SSE).")
    parser.add_argument(
        "--computer-id",
        "-c",
        default=None,
        help="Computer session id. Default: latest session from GET /computers.",
    )
    parser.add_argument(
        "--session-type",
        choices=("live", "persistent"),
        default=None,
        help="Forwarded to GET /computers type= filter when listing or picking latest.",
    )
    parser.add_argument("--list-sessions", action="store_true", help="Print sessions (TSV) and exit.")
    parser.add_argument(
        "--mode",
        choices=("log", "raw_sse", "h264", "jpeg"),
        default="log",
        help="log: one summary line per frame/event on stderr; raw_sse: passthrough; "
        "h264/jpeg: decoded video bytes to stdout (binary).",
    )
    parser.add_argument(
        "--log-to-stdout",
        action="store_true",
        help="With --mode log, write summaries to stdout instead of stderr.",
    )
    args = parser.parse_args()
    _require_env("TZAFON_API_KEY")

    client = Lightcone()

    if args.list_sessions:
        list_sessions(client, args.session_type)
        return

    cid = resolve_computer_id(client, args.computer_id, args.session_type)
    timeout = _screencast_timeout()

    try:
        with client.computers.with_streaming_response.retrieve_screencast(cid, timeout=timeout) as api_resp:
            if api_resp.status_code != 200:
                body = api_resp.http_response.text
                print(
                    f"Screencast HTTP {api_resp.status_code}: {body[:2000]}",
                    file=sys.stderr,
                )
                sys.exit(4)
            hr = api_resp.http_response
            if args.mode == "raw_sse":
                run_raw_sse(hr)
                return

            log_stream = sys.stdout if args.log_to_stdout else sys.stderr
            bin_out = sys.stdout.buffer
            for event, data in iter_sse_events(hr.iter_lines()):
                if args.mode == "log":
                    handle_payload_log(log_stream, event, data)
                else:
                    try:
                        handle_payload_pipe(bin_out, event, data, fmt=args.mode)
                    except (json.JSONDecodeError, KeyError) as exc:
                        print(f"skip malformed chunk: {exc}", file=sys.stderr, flush=True)
    except httpx.ReadTimeout:
        print(
            "HTTP read timed out waiting for the next screencast chunk. "
            "Increase LIGHTCONE_SCREENCAST_READ_TIMEOUT_SEC.",
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
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
