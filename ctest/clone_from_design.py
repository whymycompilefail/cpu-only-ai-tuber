#!/usr/bin/env python
"""Feed each VoiceDesign output through the 0.6B Base clone that actually runs.

VoiceDesign 1.7B is 15-25 s per line on this CPU -- unusable on stream, where we
have 3-5 s. So its audio is only ever a REFERENCE for the 0.6B Base model the
stack really runs. The question this script answers is the one that decides
whether any of the voice-design work is worth anything:

    how much of the designed voice survives the clone?

We already know two partial answers:
  - timbre: only 1 of the 4 Kokoro women kept its own pitch through cloning,
    the other three got dragged back to the model's prior. Inheritance is
    unreliable, not guaranteed.
  - speed: ~80% of a reference's tempo carries over.
So measure both again here, on the same sentence, and compare each clone against
its own source rather than against a global average.

Uses the q8_0 weights because that is what the running stack loads, so whatever
comes out of here is what would actually be heard on stream.

usage:
  Open-LLM-VTuber/.venv/Scripts/python.exe ctest/clone_from_design.py
"""
import glob
import os
import subprocess
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import librosa
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "llama.cpp", "build", "bin", "llama-tts.exe")
M = os.path.join(ROOT, "models", "Qwen3-TTS-0.6B-q8_0.gguf")
MM = os.path.join(ROOT, "models", "mmproj-Qwen3-TTS-0.6B-q8_0.gguf")
SRC = os.path.join(ROOT, "ctest", "voice_ab", "voicedesign")
OUT = os.path.join(SRC, "cloned")
os.makedirs(OUT, exist_ok=True)

TEXT = "诶，你又来啦，我还以为你把我忘了呢。"


def stats(path):
    y, sr = librosa.load(path, sr=None)
    f, v, _ = librosa.pyin(y, fmin=80, fmax=600, sr=sr)
    f = f[v][~np.isnan(f[v])]
    return len(y) / sr, float(np.median(f)) if len(f) else float("nan")


print(f"{'':10} {'源(设计)':>16}   {'克隆后':>16}   保留")
for src in sorted(glob.glob(os.path.join(SRC, "*.wav"))):
    name = os.path.basename(src)[:-4]
    dest = os.path.join(OUT, name + ".wav")
    subprocess.run([BIN, "-m", M, "-mm", MM, "--tts-lang", "zh", "-t", "12",
                    "-n", "96", "-s", "1", "--tts-speaker-file", src,
                    "-o", dest, "-p", TEXT],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(dest):
        print(f"{name:10} FAILED")
        continue
    d0, f0 = stats(src)
    d1, f1 = stats(dest)
    # keep the source next to its clone so the pair can be A/B'd without hunting
    sf.write(os.path.join(OUT, name + "_src.wav"),
             *librosa.load(src, sr=None)[::1], subtype="PCM_16")
    print(f"{name:10} {d0:5.2f}s {f0:6.0f}Hz   {d1:5.2f}s {f1:6.0f}Hz   "
          f"时长 {d1/d0*100:5.1f}%  音高 {f1/f0*100:5.1f}%", flush=True)

print("\nin", OUT)
