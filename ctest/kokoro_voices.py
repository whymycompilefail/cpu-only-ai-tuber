"""Generate Kokoro Chinese-female samples, both for listening and as clone references.

Kokoro-82M is Apache-2.0 (code + weights + voices), so unlike edge-tts output these
clips are clean to use as a voice-clone reference -- no ToS grey area.

Runs in the isolated venv (the repo-root .venv-kokoro) because installing
kokoro-onnx into the main venv would bump numpy 1.26.4 -> 2.5.3.

Model file comes from hf-mirror (15s) not GitHub releases (>10min).
Voices: the repo ships one raw float32 (510,256) blob per voice; kokoro_onnx wants a
single .npz keyed by voice name, so we pack the four Chinese women into one here.

usage:
  .venv-kokoro/Scripts/python.exe ctest/kokoro_voices.py
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KD = os.path.join(ROOT, "models", "kokoro")
OUT = os.path.join(ROOT, "ctest", "voice_ab", "kokoro")
os.makedirs(OUT, exist_ok=True)

# hf-mirror copy first; the GitHub-release download is far slower.
MODEL = None
for cand in ("model_hf.onnx", "kokoro-v1.0.onnx"):
    p = os.path.join(KD, cand)
    if os.path.exists(p) and os.path.getsize(p) > 300e6:
        MODEL = p
        break
if MODEL is None:
    sys.exit("no complete kokoro model in models/kokoro/")

# z = Chinese, f = female.  zf_xiaoyi is the Apache-2.0 counterpart of the
# edge zh-CN-XiaoyiNeural the user already approved, which is why it comes first.
NAMES = ["zf_xiaoyi", "zf_xiaoxiao", "zf_xiaoni", "zf_xiaobei"]
NPZ = os.path.join(KD, "voices_zh.npz")
if not os.path.exists(NPZ):
    packed = {}
    for n in NAMES:
        raw = os.path.join(KD, f"v_{n}.bin")
        if not os.path.exists(raw):
            sys.exit(f"missing {raw}")
        # (510, 1, 256) not (510, 256): the lib does voice[n] and the ONNX model
        # wants a rank-2 style, so a missing middle dim gives "Invalid rank for
        # input: style Got: 1".  Same element count, so file size can't tell you.
        packed[n] = np.fromfile(raw, dtype=np.float32).reshape(510, 1, 256)
    np.savez(NPZ, **packed)

from kokoro_onnx import Kokoro  # noqa: E402
import soundfile as sf  # noqa: E402
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")

# Identical text for every voice: cross-voice comparison is only valid on same text.
TEXT = "诶，你又来啦，我还以为你把我忘了呢。"

# espeak has no "zh"; Mandarin is "cmn".  Output lands at 24 kHz, same as our stack.
LANG = "cmn"

k = Kokoro(MODEL, NPZ)
print("model:", os.path.basename(MODEL))
for v in NAMES:
    samples, sr = k.create(TEXT, voice=v, lang=LANG, speed=1.0)
    path = os.path.join(OUT, f"{v}.wav")
    sf.write(path, samples, sr, subtype="PCM_16")
    print(f"{v:14} {len(samples)/sr:5.2f}s  sr={sr}  -> {path}")
