"""Multi-turn end-to-end probe on ONE websocket connection.

Same connection = shared conversation history, so this reproduces what the user
actually experiences: repeated answers across turns, emotion tags leaking into
the audio, and drifting voices.

Each turn's audio is saved as e2e_mt_<n>_<i>.wav for later ASR verification.
"""

import base64
import json
import sys
import time

import websocket
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

URL = "ws://127.0.0.1:12393/client-ws"
OUTDIR = ROOT + "/ctest"

PROMPTS = [
    "你好",
    "今天天气怎么样",
    "讲个笑话",
    "你喜欢什么颜色",
    "你是谁",
]


def drain(ws_, seconds=3):
    """Read and discard whatever is still queued so the next turn starts clean."""
    end = time.time() + seconds
    ws_.sock.settimeout(0.5)
    while time.time() < end:
        try:
            raw = ws_.recv()
        except Exception:
            break
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        print("    drain: %s" % msg.get("type", "?"))
    ws_.sock.settimeout(180)


def norm(ws_, text):
    """Run one turn; return list of wav bytes, first-audio time, total, done."""
    ws_.send(json.dumps({"type": "text-input", "text": text}))
    t0 = time.time()
    chunks = []
    first = None
    done = False
    while time.time() - t0 < 120:
        raw = ws_.recv()
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        t = msg.get("type", "?")
        if "audio" in msg and isinstance(msg.get("audio"), str):
            try:
                data = base64.b64decode(msg["audio"])
                chunks.append(data)
                if first is None:
                    first = time.time() - t0
            except Exception:
                pass
        if t in ("backend-synth-complete", "conversation-chain-end"):
            done = True
            break
    return chunks, first, time.time() - t0, done


def main():
    ws_ = websocket.create_connection(URL, timeout=180)
    ws_.recv()  # connection established

    n = int(sys.argv[1]) if len(sys.argv) > 1 else len(PROMPTS)
    tag = sys.argv[2] if len(sys.argv) > 2 else "mt"
    for i, p in enumerate(PROMPTS[:n]):
        drain(ws_)
        chunks, first, total, done = norm(ws_, p)
        print("\n=== %s turn %d: %s ===" % (tag, i, p))
        print("first audio %.2fs | total %.2fs | chunks %d | done %s"
              % (first or -1, total, len(chunks), done))
        for j, data in enumerate(chunks):
            path = "%s/e2e_%s_%d_%d.wav" % (OUTDIR, tag, i, j)
            with open(path, "wb") as f:
                f.write(data)
            print("  %s  %.2fs audio" % (path, max(len(data) - 44, 0) / 48000.0))
    ws_.close()


if __name__ == "__main__":
    main()
