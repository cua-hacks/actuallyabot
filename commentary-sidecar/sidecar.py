"""Commentary sidecar: listens for actuallyabot events on stdin, narrates the
agent's play in first person via Grok + ElevenLabs.

Usage:
    python -u -m actuallyabot.main --game checkers_custom --url ... 2>&1 \\
        | python -u commentary-sidecar/sidecar.py

The sidecar passes ALL stdin lines through to its own stdout (so you still
see the player's logs). On top of that:

  - **Turn events** trigger commentary on every successful move (turn_end with
    reason=stop_signal) and on game_over.
  - **Filler** fires at random 3–5s intervals when nothing else is happening
    (e.g. opponent is taking a long time). Capped to MAX_CONSECUTIVE_FILLERS
    so it doesn't drone forever.

Audio is played one clip at a time via afplay/mpg123/ffplay.
"""
from __future__ import annotations

import json
import os
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv()

XAI_API_KEY = os.environ.get("XAI_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "HaUDdkOAoitiVjpiet1i")
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4-fast-non-reasoning")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")

FILLER_INTERVAL_MIN_S = 6.0
FILLER_INTERVAL_MAX_S = 14.0
SILENCE_AFTER_REAL_S = 6.0      # don't fire filler within N seconds of a real event
MAX_CONSECUTIVE_FILLERS = 3     # then go silent until next real event

PLAYER_AUDIO = (
    "afplay" if shutil.which("afplay")
    else "mpg123" if shutil.which("mpg123")
    else "ffplay" if shutil.which("ffplay")
    else None
)

SYSTEM_PROMPT = """You are an AI checkers agent live-streaming the game on Twitch.
Narrate IN FIRST PERSON, as the player making the moves. The opponent is
NOT in the room with you — you're talking ABOUT them to the chat / camera,
not TO them. Match this energy:

  * Witty, toxic-but-playful, streamer slang. Trash talk the opponent.
  * NEVER use "you" or "your" to address the opponent. Refer to them in
    THIRD PERSON: "he", "him", "his", "this guy", "this dude", "bro",
    "my opp", "this clown", "the goon". You can address the chat with "y'all"
    or "chat" if you want, but the opponent is always third person.
  * 1 short sentence, 8-18 words. Never longer. NEVER more than one sentence.
  * Lowercase, casual. Use slang naturally: ez, ggez, free, washed, cooked,
    locked in, on god, no cap, ratio, mid, get clipped, skill issue, L,
    sit down, couldn't be me, watch this, calm down it's just checkers.
  * React to WHAT JUST HAPPENED or to the WAIT. Don't be generic.
  * If I captured: gloat. If I advanced: confident. If a move failed:
    cope. If I'm waiting on opp: dunk on his slow play.

Examples (riff, don't copy — note the third-person opponent):
  - "ez clap, free piece in the bag, this guy is washed"
  - "yo i didn't even need to try, bro is COOKED"
  - "watch this chat, i'm cooking him slowly"
  - "skill issue on his end ngl"
  - "lmao back row about to be MINE, this dude is finished"
  - "bro pick a move already, my battery is dying"
  - "did he afk? hello? anyone home in there?"
  - "this clown took 12 seconds to give me a free piece, ratio"

Output ONLY the commentary line. No quotes, no labels, no explanation."""


# ---- shared state for the threads ----
audio_queue: queue.Queue[str | None] = queue.Queue()
state_lock = threading.Lock()
last_real_event_ts: float = 0.0
consecutive_fillers: int = 0
agent_mid_turn: bool = False   # True between turn_start and turn_end


def _grok(user_msg: str) -> str | None:
    if not XAI_API_KEY:
        return None
    try:
        with httpx.Client(timeout=12.0) as c:
            r = c.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROK_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 60,
                    "temperature": 0.95,
                },
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text.startswith(('"', "'")) and text.endswith(('"', "'")):
                text = text[1:-1]
            return text
    except httpx.HTTPError as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[commentary] grok error: {e} body={body[:200]}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[commentary] grok error: {e!r}", file=sys.stderr, flush=True)
    return None


def commentate_turn(event: dict) -> str | None:
    payload = event.get("payload", {}) or {}
    reason = payload.get("reason")
    final_message = payload.get("final_message") or ""
    turn = payload.get("turn")
    steps = payload.get("steps")

    user_msg = (
        f"Turn {turn} just finished. Outcome reason: {reason}. "
        f"My move took {steps} clicks."
    )
    if final_message:
        user_msg += f"\n\nMy internal thought during the move: {final_message[:300]}"
    user_msg += "\n\nGive your one-line commentary now."
    return _grok(user_msg)


def commentate_filler() -> str | None:
    user_msg = (
        "It's been a while since the last move. The opponent is still thinking "
        "(or maybe they're cooked). React to the wait — be impatient, dunk on "
        "their slow play, or muse about the silence. One short line."
    )
    return _grok(user_msg)


def speak(text: str) -> None:
    if not ELEVENLABS_API_KEY:
        return
    if not PLAYER_AUDIO:
        print("[commentary] no audio player on PATH (need afplay/mpg123/ffplay)", file=sys.stderr, flush=True)
        return
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "accept": "audio/mpeg",
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
                    "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.6},
                },
            )
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(r.content)
                path = f.name
        try:
            cmd = [PLAYER_AUDIO]
            if PLAYER_AUDIO == "ffplay":
                cmd += ["-nodisp", "-autoexit", "-loglevel", "quiet"]
            cmd.append(path)
            subprocess.run(cmd, check=False)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except httpx.HTTPError as e:
        body = getattr(getattr(e, "response", None), "text", "")
        print(f"[commentary] tts error: {e} body={body[:200]}", file=sys.stderr, flush=True)


def parse_event_line(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("[event]"):
        return None
    try:
        return json.loads(line[len("[event]"):].strip())
    except json.JSONDecodeError:
        return None


def should_commentate_turn(event: dict) -> bool:
    t = event.get("type")
    payload = event.get("payload", {}) or {}
    if t == "game_over":
        return True
    if t != "turn_end":
        return False
    return payload.get("reason") == "stop_signal"


def audio_worker() -> None:
    while True:
        text = audio_queue.get()
        if text is None:
            return
        speak(text)


def filler_loop() -> None:
    global last_real_event_ts, consecutive_fillers
    while True:
        time.sleep(random.uniform(FILLER_INTERVAL_MIN_S, FILLER_INTERVAL_MAX_S))
        with state_lock:
            since_real = time.time() - last_real_event_ts
            cap_hit = consecutive_fillers >= MAX_CONSECUTIVE_FILLERS
            mid_turn = agent_mid_turn
        if mid_turn:
            continue  # don't talk while we're actively making a move
        if since_real < SILENCE_AFTER_REAL_S:
            continue
        if cap_hit:
            continue
        if not audio_queue.empty():
            continue  # don't pile up

        text = commentate_filler()
        if not text:
            continue
        with state_lock:
            consecutive_fillers += 1
        print(f"[commentary/filler] {text}", flush=True)
        audio_queue.put(text)


def main() -> None:
    global last_real_event_ts, consecutive_fillers, agent_mid_turn

    print(
        f"[commentary-sidecar] up. grok={'ok' if XAI_API_KEY else 'MISSING'} "
        f"tts={'ok' if ELEVENLABS_API_KEY else 'MISSING'} player={PLAYER_AUDIO or 'MISSING'}",
        flush=True,
    )
    # Start the audio worker FIRST so the queue has a consumer.
    threading.Thread(target=audio_worker, daemon=True).start()
    threading.Thread(target=filler_loop, daemon=True).start()

    # Initialize so we don't fire filler in the first ~6s of startup either.
    with state_lock:
        last_real_event_ts = time.time()

    for line in sys.stdin:
        sys.stdout.write(line)
        sys.stdout.flush()

        event = parse_event_line(line)
        if event is None:
            continue

        # Track "agent is in the middle of a move" so fillers don't fire
        # while we're actively clicking through the move sequence.
        etype = event.get("type")
        if etype == "turn_start":
            with state_lock:
                agent_mid_turn = True
            continue
        if etype == "turn_end":
            with state_lock:
                agent_mid_turn = False

        if not should_commentate_turn(event):
            continue

        text = commentate_turn(event)
        with state_lock:
            last_real_event_ts = time.time()
            consecutive_fillers = 0
        if not text:
            continue
        print(f"[commentary] {text}", flush=True)
        audio_queue.put(text)


if __name__ == "__main__":
    main()
