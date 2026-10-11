#!/usr/bin/env python
"""Produce the final blind-listen set for the 少女音 decision.

One sentence for every file (cross-text F0 numbers are meaningless -- a laugh in
the line moved the same voice from 318 to 413 Hz in an earlier run), fixed seed
(the engine wanders in timbre when seed is left at -1), and one variable only:
how many semitones of transpose is applied on top of the clone.

Reference is Kokoro `zf_xiaoyi` (Apache-2.0), i.e. the licensable counterpart of
the edge zh-CN-XiaoyiNeural voice the user already liked. It is the only
reference measured to survive cloning with its own pitch intact (311 Hz), the
other three Kokoro women get dragged back to the model prior.

usage:
  python ctest/make_listen.py            # synth once, then derive every transpose
"""
import importlib.util
import os
import subprocess
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import librosa
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "llama.cpp", "build", "bin", "llama-tts.exe")
M = os.path.join(ROOT, "models", "Qwen3-TTS-0.6B-f16.gguf")
MM = os.path.join(ROOT, "models", "mmproj-Qwen3-TTS-0.6B-f16.gguf")
REF = os.path.join(ROOT, "ctest", "voice_ab", "kokoro", "zf_xiaoyi.wav")
OUT = os.path.join(ROOT, "ctest", "voice_ab", "listen")
os.makedirs(OUT, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "pm", os.path.join(ROOT, "Open-LLM-VTuber", "src", "open_llm_vtuber", "utils", "pitch.py"))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

# A line she would actually say on stream, and the same line Kokoro spoke, so the
# reference and the clone are directly comparable.
TEXT = "诶，你又来啦，我还以为你把我忘了呢。"
SEED = 1

print(f"ref   : {REF}")
print(f"text  : {TEXT}")
print(f"seed  : {SEED}\n")

raw = os.path.join(OUT, "_raw_p0.wav")
cmd = [BIN, "-m", M, "-mm", MM, "--tts-lang", "zh", "-t", "12", "-n", "96",
       "-s", str(SEED), "--tts-speaker-file", REF, "-o", raw, "-p", TEXT]
print("synth ...", flush=True)
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if not os.path.exists(raw):
    raise SystemExit("llama-tts produced nothing")


def f0(path):
    y, sr = librosa.load(path, sr=None)
    f, v, _ = librosa.pyin(y, fmin=80, fmax=600, sr=sr)
    f = f[v][~np.isnan(f[v])]
    return float(np.median(f)) if len(f) else float("nan")


def dur(path):
    return len(librosa.load(path, sr=None)[0]) / librosa.load(path, sr=None)[1]


STEPS = [0, 2, 3, 4, 5]
print(f"{'file':16} {'半音':>4}  {'F0':>7}  {'时长':>5}")
rows = []
for st in STEPS:
    name = f"xiaoyi_p{st}"
    dest = os.path.join(OUT, name + ".wav")
    if st == 0:
        y, sr = librosa.load(raw, sr=None)
    else:
        y, sr = librosa.load(raw, sr=None)
        y = np.clip(pm.shift_semitones(y, float(st), sr=sr), -1, 1)
    sf.write(dest, (y * 32767).astype(np.int16), sr, subtype="PCM_16")
    f, d = f0(dest), dur(dest)
    rows.append((name, st, f, d))
    print(f"{name:16} +{st:<3}  {f:7.1f}  {d:5.2f}s   -> {dest}")

# the reference itself, so the user can hear what we were cloning *from*
import shutil
shutil.copy(REF, os.path.join(OUT, "ref_kokoro_zf_xiaoyi.wav"))
print(f"\n{'ref_kokoro':16}  --    {f0(REF):7.1f}  {dur(REF):5.2f}s   (Kokoro 原声, 克隆源)")

os.remove(raw)
print("\nall files in", OUT)
