"""End-to-end probe: send one text message into the VTuber websocket and
report every stage until audio comes back."""

import base64
import json
import sys
import time

import websocket
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

URL = "ws://127.0.0.1:12393/client-ws"
TEXT = sys.argv[1] if len(sys.argv) > 1 else "你好，请用一句话做个自我介绍。"

start = time.time()
seen = []
audio = []


def log(kind, payload):
    dt = time.time() - start
    print("[%6.2fs] %-28s %s" % (dt, kind, payload), flush=True)


ws = websocket.create_connection(URL, timeout=180)
log("connected", URL)

# some versions expect a hello/config first; send the text trigger either way
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
            v = str(msg[k])
            extra = v[:60]
            break
    if "audio" in msg and msg["audio"]:
        a = msg["audio"]
        if isinstance(a, str):
            try:
                audio.append(base64.b64decode(a))
                extra = "audio b64 %d chars" % len(a)
            except Exception:
                extra = "audio field non-b64"
        elif isinstance(a, list):
            extra = "audio list len %d" % len(a)
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
if audio:
    # each chunk is a complete WAV (own header); concatenating them would
    # produce a file that only plays the first one
    for i, a in enumerate(audio):
        out = ROOT + "/ctest/e2e_reply_%d.wav" % i
        with open(out, "wb") as f:
            f.write(a)
        print("wrote %s (%d bytes, %.2fs audio)"
              % (out, len(a), max(len(a) - 44, 0) / 48000.0))
    sys.exit(0)
sys.exit(1)
