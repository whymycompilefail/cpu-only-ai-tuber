#!/usr/bin/env python3
"""Does a reply reach ALL connected clients, or only the one that asked?

This decides the whole live-stream architecture:

  If the backend broadcasts -> a headless danmaku bridge can inject messages and
  the browser (what the audience sees/hears) will play them.  Bridge as a
  separate WebSocket client works.

  If the backend replies only to the sender -> the bridge's replies go into a
  socket nobody is watching.  The browser would show a frozen character and
  play no audio.  We would then need group conversation, or to inject the
  danmaku into the page itself.

Method: open two connections, send from A, record what B receives.
"""

import asyncio
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

URL = "ws://127.0.0.1:12393/client-ws"


async def watcher(name: str, ws, seconds: float, sink: list):
    end = time.time() + seconds
    while time.time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except Exception:
            return
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        t = msg.get("type", "?")
        text = msg.get("text", "")
        note = f"{t}" + (f":{text[:40]}" if text else "")
        if "audio" in msg:
            note += f" [audio {len(msg.get('audio',''))}b]"
        if t not in ("full-text",) or "Thinking" not in str(text):
            sink.append((name, t, note))
            print(f"  {name}: {note}", flush=True)


async def main():
    print("opening two clients A (sender) and B (observer)...", flush=True)
    async with ws_connect(URL, open_timeout=15) as a, \
            ws_connect(URL, open_timeout=15) as b:
        await a.recv()
        await b.recv()
        print("both connected\n", flush=True)

        sink: list = []
        t = asyncio.ensure_future(watcher("B", b, 25, sink))

        await asyncio.sleep(1)
        print("A sends: '你好，给大家打个招呼'", flush=True)
        await a.send(json.dumps({"type": "text-input",
                                 "text": "你好，给大家打个招呼"}))

        # also drain A so it can complete its handshake
        async def drain_a():
            for _ in range(60):
                try:
                    msg = json.loads(await asyncio.wait_for(a.recv(), timeout=1))
                except Exception:
                    continue
                if msg.get("type") == "backend-synth-complete":
                    await a.send(json.dumps(
                        {"type": "frontend-playback-complete"}))
                if msg.get("type") == "control" and \
                        msg.get("text") == "conversation-chain-end":
                    return
        await asyncio.gather(drain_a(), t)

        kinds = {k for _, k, _ in sink if k}
        print("\n" + "=" * 60)
        print(f"B (observer) saw message types: {sorted(kinds)}")
        audio = [s for s in sink if s[1] != "full-text" and "[audio" in s[2]]
        if audio:
            print("VERDICT: BROADCAST -- a headless bridge works as-is.")
        else:
            print("VERDICT: SENDER-ONLY -- replies do not reach other clients.")
            print("         A separate bridge would be invisible and silent.")
        print("=" * 60)
        return 0 if audio else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
