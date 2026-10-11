"""End-to-end probe for the local VTuber stack.

Sends one text message into the backend websocket and reports every stage until
audio comes back, with timings. Usage:

    python e2e_zh.py "can you speak chinese"
    python e2e_zh.py                 # default Chinese greeting
"""

import base64
import json
import sys
import time

import websocket
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

URL = "ws://127.0.0.1:12393/client-ws"
TEXT = sys.argv[1] if len(sys.argv) > 1 else "你好，请用一句话做个自我介绍。"
OUT = ROOT + "/ctest/e2e_%s.wav"

start = time.time()
seen = []
audio = []
first_audio_at = None


def log(kind, payload):
    dt = time.time() - start
    print("[%6.2fs] %-28s %s" % (dt, kind, payload), flush=True)


ws = websocket.create_connection(URL, timeout=180)
log("connected", URL)

ws.send(json.dumps({"type": "text-input", "text": TEXT}))
log("sent", TEXT)

deadline = time.time() + 150
while time.time() < deadline:
    try:
        raw = ws.recv()
    except Exception as e:
        log("recv error", str(e))
        break
    try:
        msg = json.loads(raw)
    except Exception:
        log("raw", raw[:80])
        continue

    t = msg.get("type", "?")
    seen.append(t)
    extra = ""
    for k in ("text", "name", "display_text", "sentence"):
        if k in msg:
            extra = str(msg[k])[:80]
            break
    if "audio" in msg and msg["audio"]:
        a = msg["audio"]
        if isinstance(a, str):
            try:
                data = base64.b64decode(a)
                audio.append(data)
                if first_audio_at is None:
                    first_audio_at = time.time() - start
                extra = "audio %d bytes (%.2fs)" % (
                    len(data), max(len(data) - 44, 0) / 48000.0)
            except Exception:
                extra = "audio non-b64"
        else:
            extra = "audio type %s" % type(a).__name__
    log(t, extra)

    if t in ("backend-synth-complete", "ai-speak-signal-complete",
             "force-new-message"):
        if audio:
            break
    if time.time() - start > 140:
        break

ws.close()

print("\nmessage types seen:", sorted(set(seen)))
print("audio chunks:", len(audio), "total bytes:", sum(len(a) for a in audio))
if first_audio_at:
    print("FIRST AUDIO AT %.2fs" % first_audio_at)
print("TOTAL %.2fs" % (time.time() - start))

if audio:
    tag = "en" if len(sys.argv) > 1 else "zh"
    for i, a in enumerate(audio):
        out = OUT % ("%s_%d" % (tag, i))
        with open(out, "wb") as f:
            f.write(a)
        print("wrote %s (%d bytes, %.2fs audio)"
              % (out, len(a), max(len(a) - 44, 0) / 48000.0))
    sys.exit(0)
sys.exit(1)
