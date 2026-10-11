#!/usr/bin/env python3
"""Simulate the injected browser page and verify the full danmaku loop.

Mirrors exactly what frontend/danmaku_inject.js does, in Python, so the
architecture can be tested without a browser:

    page -> backend /client-ws   (this is what shows video + plays audio)
    page -> bridge  /inject      (receives danmaku to speak)

The assertion that matters: after the bridge pushes a danmaku, the AUDIO must
come back on the *page's* backend socket.  If audio only ever arrived on the
bridge's own socket, the audience would see nothing and hear nothing.

Usage:  python ctest/test_inject_loop.py   (stack + bridge must be running)
"""

import asyncio
import base64
import json
import os
import sys
import time

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    from websockets.legacy.client import connect as ws_connect

BACKEND = "ws://127.0.0.1:12393/client-ws"
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8765"))
BRIDGE = f"ws://127.0.0.1:{BRIDGE_PORT}/inject"


async def main() -> int:
    print("=== simulated page: connecting to backend + bridge ===", flush=True)
    async with ws_connect(BACKEND, open_timeout=15) as page_ws, \
            ws_connect(BRIDGE, open_timeout=15) as bridge_ws:
        await page_ws.recv()          # "Connection established"
        await bridge_ws.send(json.dumps({"hello": True}))
        print("both connected\n", flush=True)

        audio_on_page: list[int] = []
        spoken: list[str] = []
        done = asyncio.Event()

        async def page_listener():
            """What the real page does: play audio, answer the handshake."""
            while True:
                raw = await page_ws.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", "replace")
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                t = m.get("type")
                if isinstance(m.get("audio"), str) and m["audio"]:
                    audio_on_page.append(len(base64.b64decode(m["audio"])))
                    print(f"  [page] AUDIO {len(m.get('audio',''))} b64 chars",
                          flush=True)
                elif t == "full-text" and m.get("text"):
                    txt = m["text"]
                    if txt not in ("Thinking...", "Connection established"):
                        spoken.append(txt)
                        print(f"  [page] text: {txt[:60]}", flush=True)
                elif t == "backend-synth-complete":
                    await page_ws.send(json.dumps(
                        {"type": "frontend-playback-complete"}))
                    await bridge_ws.send(json.dumps(
                        {"event": "backend-synth-complete"}))
                elif t == "control" and m.get("text") == "conversation-chain-end":
                    await bridge_ws.send(json.dumps(
                        {"event": "conversation-chain-end"}))
                    done.set()

        async def bridge_listener():
            """On {'send': text}, write it into the page socket."""
            while True:
                raw = await bridge_ws.recv()
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                if m.get("send"):
                    print(f"  [bridge->page] {m['send']}", flush=True)
                    await page_ws.send(json.dumps(
                        {"type": "text-input", "text": m["send"]}))

        listener = asyncio.ensure_future(page_listener())
        asyncio.ensure_future(bridge_listener())

        # Now the danmaku source: POST a few to the bridge's HTTP intake.
        print("\n=== posting danmaku to bridge ===", flush=True)
        import urllib.request
        body = json.dumps([
            {"user": "viewer1", "text": "66666"},          # noise, dropped
            {"user": "viewer2", "text": "主播你好呀"},        # kept
        ]).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{BRIDGE_PORT}/danmaku", data=body,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
        print("posted 2 (1 is noise)\n", flush=True)

        try:
            await asyncio.wait_for(done.wait(), timeout=90)
        except asyncio.TimeoutError:
            print("TIMED OUT waiting for conversation-chain-end", flush=True)

        listener.cancel()
        await asyncio.sleep(0.5)

        print("\n" + "=" * 62)
        print(f"audio chunks received on PAGE socket : {len(audio_on_page)}")
        print(f"bytes                               : {sum(audio_on_page)}")
        print(f"spoken text seen on page            : {spoken}")
        ok = len(audio_on_page) > 0
        print("VERDICT:", "PASS - the audience would hear it"
              if ok else "FAIL - audio never reached the page")
        print("=" * 62)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
