#!/usr/bin/env python
"""Blind-listen candidates for the "少女音 via speaker reference" idea.

Two things this script is careful about:

1. ONE sentence for every candidate. Measured F0 moves a lot with what is being
   said -- a line with a laugh in it came out at 413 Hz where the same voice on a
   flat sentence was 318 Hz. Cross-sentence numbers are not comparable, so every
   candidate here speaks the same line.

2. Voice *stability* is measured separately from pitch height. A reference is
   useless for a live stream if the voice wanders from line to line, so we also
   synthesise the same text with different seeds and look at the spread.

References:
  SPK1  our current reference (TTS output from this very model -> in-distribution)
  XY    edge zh-CN-XiaoyiNeural, a single sentence (~4 s) -> out-of-distribution
  BOOT  SPK1 transposed +3 and fed back as a reference -> out-of-distribution,
        but produced entirely locally, no cloud involved
"""
import os
import subprocess
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import librosa
import soundfile as sf
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "llama.cpp", "build", "bin", "llama-tts.exe")
M = os.path.join(ROOT, "models", "Qwen3-TTS-0.6B-f16.gguf")
MM = os.path.join(ROOT, "models", "mmproj-Qwen3-TTS-0.6B-f16.gguf")
OUT = os.path.join(ROOT, "ctest", "voice_ab", "refcand")
os.makedirs(OUT, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "pm", os.path.join(ROOT, "Open-LLM-VTuber", "src", "open_llm_vtuber", "utils", "pitch.py"))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

SPK1 = os.path.join(ROOT, "models", "speaker_refs", "spk_1.wav")
XY = os.path.join(ROOT, "ctest", "voice_ab", "refs", "ref_xy_one.wav")
BOOT = os.path.join(ROOT, "ctest", "voice_ab", "refs", "ref_spk1_p3.wav")

TEXT = "今天天气真不错呀，我们出去玩吧。"


def synth(text, ref, name, seed=1):
    dest = os.path.join(OUT, name + ".wav")
    cmd = [BIN, "-m", M, "-mm", MM, "--tts-lang", "zh", "-t", "12",
           "-n", "96", "-s", str(seed), "-o", dest, "-p", text]
    if ref:
        cmd += ["--tts-speaker-file", ref]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dest


def transpose(src, semitones, name):
    y, sr = librosa.load(src, sr=None)
    dest = os.path.join(OUT, name + ".wav")
    sf.write(dest, (np.clip(pm.shift_semitones(y, semitones, sr=sr), -1, 1) * 32767)
             .astype(np.int16), sr, subtype="PCM_16")
    return dest


def f0(path):
    y, sr = librosa.load(path, sr=None)
    f, v, _ = librosa.pyin(y, fmin=80, fmax=600, sr=sr)
    f = f[v]
    f = f[~np.isnan(f)]
    return float(np.median(f)) if len(f) else float("nan")


print("=== 1. 稳定性：同一句文本，换 seed，看音色漂移多少 ===")
for label, ref in (("spk_1(现状)", SPK1), ("Xiaoyi", XY)):
    vals = []
    for s in (1, 2, 3):
        p = synth(TEXT, ref, f"stab_{'spk1' if ref == SPK1 else 'xy'}_s{s}", seed=s)
        vals.append(f0(p))
    print(f"  {label:12} seed1/2/3 = " + " ".join(f"{v:.0f}" for v in vals)
          + f"   极差 {max(vals)-min(vals):.0f} Hz")

print(f"\n=== 2. 盲听候选（全部同一句：「{TEXT}」）===")
CANDS = [
    ("A_spk1_p0", SPK1, 0.0),   # 旧默认，成年女声
    ("B_spk1_p3", SPK1, 3.0),   # 现在在跑的
    ("C_xy_p0",   XY,   0.0),   # 你的思路，原样
    ("D_xy_p1",   XY,   1.0),
    ("E_boot_p0", BOOT, 0.0),   # 自举：自己的输出移调后当参考，纯本地
]
for name, ref, st in CANDS:
    raw = synth(TEXT, ref, name + "_raw")
    final = transpose(raw, st, name) if st else raw
    print(f"  {name:12} +{st:.0f} 半音   F0 {f0(final):6.1f} Hz")
print("\ncandidates in", OUT)
