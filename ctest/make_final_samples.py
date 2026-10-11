#!/usr/bin/env python
"""Speak several different lines with the SETTLED config, for a final listen.

The single-sentence A/B picked the voice; this checks it holds up on other text.
Two things can still go wrong and one sentence cannot show either:

1. the reference (Kokoro zf_xiaoyi) is badly pronounced -- ASR reads it as
   "给你有来，老虎小还以为你包裹完了呢" for "诶，你又来啦，我还以为你把我忘了呢".
   If that sloppiness leaks into the clone we need to know now, not on stream.
2. timbre drift between lines. seed is now pinned, but a reference can still be
   unstable on some phoneme combinations.

usage:
  Open-LLM-VTuber/.venv/Scripts/python.exe ctest/make_final_samples.py
"""
import os
import subprocess
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "llama.cpp", "build", "bin", "llama-tts.exe")
M = os.path.join(ROOT, "models", "Qwen3-TTS-0.6B-f16.gguf")
MM = os.path.join(ROOT, "models", "mmproj-Qwen3-TTS-0.6B-f16.gguf")
REF = os.path.join(ROOT, "models", "speaker_refs", "kokoro_zf_xiaoyi.wav")
OUT = os.path.join(ROOT, "ctest", "voice_ab", "listen", "final")
os.makedirs(OUT, exist_ok=True)

# Lines with different lengths and different phoneme mixes: an excited one, a
# short filler, a longer explanatory one, and one with a trailing question.
LINES = [
    "诶，你又来啦，我还以为你把我忘了呢。",
    "欢迎回来，今天想聊点什么呀？",
    "刚才那条弹幕我看到了，别急，一个一个来。",
    "嗯，让我想想，这个问题有点意思。",
]

for i, text in enumerate(LINES):
    dest = os.path.join(OUT, f"s{i}.wav")
    cmd = [BIN, "-m", M, "-mm", MM, "--tts-lang", "zh", "-t", "12", "-n", "96",
           "-s", "1", "--tts-speaker-file", REF, "-o", dest, "-p", text]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok = os.path.exists(dest)
    print(f"s{i}.wav  {'ok' if ok else 'FAILED'}  ({os.path.getsize(dest)/2/24000:.2f}s)"
          f"  {text}", flush=True)
print("\nin", OUT)
