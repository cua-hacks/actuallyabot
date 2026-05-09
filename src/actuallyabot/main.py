from __future__ import annotations

import argparse
import importlib
import os

from dotenv import load_dotenv
from kernel import Kernel
from tzafon import Lightcone

from . import dom, orchestrator, session
from .events import EventPublisher


def _load_game(name: str, url_override: str | None):
    mod = importlib.import_module(f"actuallyabot.games.{name}")
    return mod.make(url_override)


def cli() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--game", default=os.environ.get("GAME", "placeholder"))
    p.add_argument("--url", default=os.environ.get("GAME_URL_OVERRIDE") or None)
    p.add_argument("--profile", default=os.environ.get("KERNEL_PROFILE") or None)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=800)
    p.add_argument("--timeout", type=int, default=1800)
    args = p.parse_args()

    game = _load_game(args.game, args.url)

    sess = session.open_session(
        viewport_width=args.width,
        viewport_height=args.height,
        timeout_seconds=args.timeout,
        profile_id=args.profile,
    )
    print(f"\n[session] id={sess.session_id}")
    print(f"[session] live_view_url={sess.browser_live_view_url}\n")
    print(f"[game] name={game.name} url={game.url}")

    k = Kernel()
    tz = Lightcone()
    publisher = EventPublisher(session_id=sess.session_id)

    try:
        dom.goto(k, sess.session_id, game.url)
        orchestrator.play(
            k=k, tz=tz,
            session_id=sess.session_id,
            game=game,
            viewport=(args.width, args.height),
            publisher=publisher,
        )
    finally:
        publisher.close()
        sess.close()


if __name__ == "__main__":
    cli()
