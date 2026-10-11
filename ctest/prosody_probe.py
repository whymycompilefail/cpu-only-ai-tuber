#!/usr/bin/env python
"""Two cheap experiments that decide which way to go for "less radio announcer".

The user's complaint is about PROSODY (it reads like an audiobook), not timbre --
timbre was settled separately. Two things could fix prosody and they have very
different costs, so measure which one actually works before building anything:

  E1  does the model obey a style instruction written INSIDE the text?
      Qwen3-TTS CustomVoice has a real `instruct` parameter, but llama-tts only
      exposes --tts-lang and --tts-speaker-file, so we cannot pass it. The docs
      also claim the model understands instructions typed into the text itself
      ("括号内停顿两秒真实静音2秒"). If Base honours that too, the fix is free.
      Failure mode is loud and obvious: it just reads the instruction out loud,
      same family as the [smirk] tag leaking into speech.

  E2  does PROSODY come through the speaker reference, or only timbre?
      We already proved pronunciation does NOT come through (the Kokoro reference
      is barely intelligible yet its clone is word-perfect). Prosody is a separate
      question and nobody checked it. Test: time-stretch the reference to 1.35x
      WITHOUT changing pitch (time-stretch, not resample -- transposing is what
      produced the robot artefacts). If the clone also speeds up, prosody is
      inherited and swapping references is a real lever. If not, the engine's own
      prior is all that matters and no reference can ever fix the reading style.

usage:
  Open-LLM-VTuber/.venv/Scripts/python.exe ctest/prosody_probe.py
"""
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
REF = os.path.join(ROOT, "models", "speaker_refs", "kokoro_zf_xiaoyi.wav")
OUT = os.path.join(ROOT, "ctest", "voice_ab", "prosody")
os.makedirs(OUT, exist_ok=True)

BASE = "诶，你又来啦，我还以为你把我忘了呢。"


def synth(text, ref, name):
    dest = os.path.join(OUT, name + ".wav")
    cmd = [BIN, "-m", M, "-mm", MM, "--tts-lang", "zh", "-t", "12", "-n", "96",
           "-s", "1", "--tts-speaker-file", ref, "-o", dest, "-p", text]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dest if os.path.exists(dest) else None


def dur(p):
    y, sr = librosa.load(p, sr=None)
    return len(y) / sr


print("=== E1: style instruction typed into the text? ===")
print(f"  baseline : {BASE}")
# Trailing instruction, one sentence, ends with a full stop -- exactly the form
# the docs describe for CustomVoice.
VARIANTS = [
    ("e1_plain", BASE),
    ("e1_cojue", BASE + "（用撒娇的语气，语速稍快）"),
    ("e1_excited", BASE + "（兴奋地，语气上扬）"),
]
for name, text in VARIANTS:
    p = synth(text, REF, name)
    print(f"  {name:12} {dur(p):5.2f}s   <- {text}")

print("\n=== E2: does the reference carry SPEED? (reference stretched 1.35x) ===")
y, sr = librosa.load(REF, sr=None)
fast = os.path.join(OUT, "ref_fast.wav")
# librosa >=0.11 made `rate` keyword-only.
sf.write(fast, librosa.effects.time_stretch(y, rate=1.35), sr, subtype="PCM_16")
print(f"  reference: {dur(REF):.2f}s -> {dur(fast):.2f}s (pitch untouched)")
for name, ref in (("e2_normal_ref", REF), ("e2_fast_ref", fast)):
    p = synth(BASE, ref, name)
    print(f"  {name:14} output {dur(p):5.2f}s")

print("\nin", OUT)
