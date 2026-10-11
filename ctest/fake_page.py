#!/usr/bin/env python3
"""Headless stand-in for the Live2D page, so the danmaku loop can be tested
without a browser.

The backend does not broadcast: a reply only goes to the socket that asked. So
something has to hold a /client-ws connection, answer the playback handshake,
and tell the bridge when the round is over -- normally that is the page. This
script is that something with the visuals removed.

    python ctest/fake_page.py                 # attach and wait
    python ctest/fake_page.py --once          # also print audio byte counts

Combine with:
    python ctest/danmaku_bridge.py --source http --port 8765
    curl -X POST localhost:8765/danmaku -d '{"user":"a","text":"米粒你会唱歌吗"}'

What it proves
--------------
G3  the page channel attaches          (bridge logs "page connected")
G4  text in -> AI sentence -> idle     (watch for "ai :" and "idle again")

It proves NOTHING about Live2D rendering or audible sound; those need a human.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time

import websocket

# This environment exports http_proxy, and websocket-client tunnels even for
# 127.0.0.1 -- it died with "failed CONNECT via proxy status: 502" here. curl
# needed --noproxy for the same reason. Strip the variables before connecting;
# a browser has no such problem, so this only ever affected the test harness.
for _k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY",
           "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "*"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BACKEND = "ws://127.0.0.1:12393/client-ws"
BRIDGE = "ws://127.0.0.1:8765/inject"


def log(kind: str, payload: str = "") -> None:
    print(f"[{time.time() - T0:6.2f}s] {kind:<26} {payload}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true",
                    help="exit after the first finished round")
    ap.add_argument("--bridge", default=BRIDGE)
    a = ap.parse_args()

    page = websocket.create_connection(BACKEND, timeout=180)
    log("page socket open", BACKEND)

    bridge = websocket.create_connection(a.bridge, timeout=180)
    bridge.send(json.dumps({"hello": True}))
    log("bridge socket open", a.bridge)

    rounds = 0
    try:
        return pump(page, bridge, rounds, a.once)
    finally:
        try:
            page.close()
        except Exception:
            pass
        try:
            bridge.close()
        except Exception:
            pass


def pump(page, bridge, rounds: int, once: bool) -> int:
    while True:
        # Bridge -> page. This is what danmaku look like from here.
        bridge.settimeout(0.2)
        try:
            raw = bridge.recv()
        except Exception:
            raw = None
        if raw:
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {}
            if msg.get("send"):
                log("IN danmaku", msg["send"])
                page.send(json.dumps({"type": "text-input",
                                      "text": msg["send"]}))

        # Page <- backend. Relay the handshake, forward lifecycle events.
        page.settimeout(0.2)
        try:
            praw = page.recv()
        except Exception:
            praw = None
        if praw:
            try:
                m = json.loads(praw)
            except Exception:
                m = {}
            mt = m.get("type")
            if mt == "audio":
                # The waveform itself, separate from the synth-complete signal.
                blob = m.get("audio") or ""
                try:
                    nbytes = len(base64.b64decode(blob or ""))
                except Exception:
                    nbytes = -1
                log("audio wav", f"{nbytes} bytes")
            elif mt == "backend-synth-complete":
                # Playback handshake: the backend blocks the chain until the
                # page says it finished playing, and it has NO timeout.
                log("playback handshake")
                page.send(json.dumps({"type": "frontend-playback-complete"}))
            elif mt == "full-text" and m.get("text"):
                log("ai says", m["text"])
            elif mt == "control" and m.get("text") == "conversation-chain-end":
                log("round complete")
                bridge.send(json.dumps({"event": "conversation-chain-end"}))
                rounds += 1
                if once:
                    return 0
            elif mt == "error":
                log("BACKEND ERROR", json.dumps(m)[:200])
            elif mt:
                log(f"back<{mt}", json.dumps(m)[:160])


T0 = time.time()

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nbye", flush=True)
