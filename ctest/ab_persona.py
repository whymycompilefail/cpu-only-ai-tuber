#!/usr/bin/env python
"""A/B the persona prompt: same inputs before and after, measure prosody.

Text drives prosody about as hard as the voice does (see the note in
ctest/voice_ab/text_effect), so changing the persona should move the numbers.
This runs a fixed set of inputs through the live stack and reports, per reply:

  - the raw text the LLM produced (so we can catch 标注 leaking into speech)
  - F0 median and F0 std ("起伏") of the synthesised audio

usage:
  Open-LLM-VTuber/.venv/Scripts/python.exe ctest/ab_persona.py <outdir>
"""
import base64
import glob
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import librosa
import websocket

URL = "ws://127.0.0.1:12393/client-ws"
OUT = sys.argv[1] if len(sys.argv) > 1 else "ctest/voice_ab/ab/before"
os.makedirs(OUT, exist_ok=True)

# deliberately mixed: greeting (statement), mood (statement), a question, a jab
INPUTS = [
    "跟大家打个招呼吧",
    "今天心情怎么样",
    "有人问我你多大了",
    "你说你能做什么",
]


def probe(text, timeout=150):
    start = time.time()
    audio, texts = [], []
    ws = websocket.create_connection(URL, timeout=180)
    ws.send(json.dumps({"type": "text-input", "text": text}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = json.loads(ws.recv())
        except Exception:
            break
        t = msg.get("type", "?")
        if t == "full-text":
            for k in ("text", "display_text", "sentence"):
                if k in msg and msg[k]:
                    texts.append(str(msg[k]))
                    break
        if t == "audio" and msg.get("audio"):
            try:
                audio.append(base64.b64decode(msg["audio"]))
            except Exception:
                pass
        if t in ("backend-synth-complete", "ai-speak-signal-complete") and audio:
            break
    ws.close()
    return audio, texts, time.time() - start


def measure(path):
    y, sr = librosa.load(path, sr=None)
    f, v, _ = librosa.pyin(y, fmin=80, fmax=600, sr=sr)
    f = f[v]
    f = f[~np.isnan(f)]
    if len(f) < 10:
        return None
    return dict(dur=len(y) / sr, f0=float(np.median(f)), std=float(np.std(f)))


rows = []
for i, text in enumerate(INPUTS):
    audio, texts, elapsed = probe(text)
    spoken = " ".join(t for t in texts if t.strip() and t.strip() != "Thinking...")
    for j, a in enumerate(audio):
        p = os.path.join(OUT, "in%d_%d.wav" % (i, j))
        with open(p, "wb") as fh:
            fh.write(a)
        m = measure(p)
        if m is None:
            continue
        m.update(i=i, j=j, prompt=text, spoken=spoken, wall=elapsed, file=p)
        rows.append(m)
        print("in%d_%d  %5.2fs  F0 %5.0f  起伏 %5.1f  | %s"
              % (i, j, m["dur"], m["f0"], m["std"], spoken[:48]), flush=True)
    if not audio:
        print("in%d  NO AUDIO (%.1fs) | %s" % (i, elapsed, spoken[:48]), flush=True)

if rows:
    print("\n--- 汇总 %d 句 ---" % len(rows))
    print("平均 F0 %.0f Hz   平均起伏 %.1f   平均时长 %.2fs"
          % (np.mean([r["f0"] for r in rows]),
             np.mean([r["std"] for r in rows]),
             np.mean([r["dur"] for r in rows])))

with open(os.path.join(OUT, "result.json"), "w") as fh:
    json.dump(rows, fh, indent=1, ensure_ascii=False)
print("saved", os.path.join(OUT, "result.json"))
