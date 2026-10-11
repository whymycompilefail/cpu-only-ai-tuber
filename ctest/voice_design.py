#!/usr/bin/env python
"""Design a voice with words instead of hunting for one.

This is the whole point of the exercise. The old pipeline needed a REAL woman's
voice and that is where it kept dying: AISHELL-3 is read-aloud studio speech,
CSMSC is non-commercial, WenetSpeech audio is owned by the original YouTube
creators, and paying a voice actress to license her voice is asking her to
compete with her own clone. VoiceDesign removes the supply chain entirely -- the
voice is synthesised from a description, so there is nobody to license and
nothing to infringe. Apache-2.0, same as the rest of Qwen3-TTS.

It is also the only source that can be asked for a SPEAKING STYLE rather than a
timbre. Every real-speech corpus we looked at is studio read-aloud, which is
exactly the "广播/有声书腔" the user is complaining about. Asking for "像在跟
朋友聊天" is something no corpus can give us.

Speed does not matter here: 1.7B on CPU is ~10-30 s per line and far too slow
for a live stream, so this script exists to produce a 3-5 s reference ONCE and
hand it to the 0.6B Base clone that actually runs on stream. That is the
official VoiceDesign -> clone flow. Runtime cost stays 3-5 s per call.

usage:
  .venv-qwentts/Scripts/python.exe ctest/voice_design.py
"""
import os
import time
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import soundfile as sf
import torch

torch.set_num_threads(22)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "Qwen3-TTS-12Hz-1.7B-VoiceDesign")
OUT = os.path.join(ROOT, "ctest", "voice_ab", "voicedesign")
os.makedirs(OUT, exist_ok=True)

# One line for everything. Same rule as always: cross-text pitch numbers are
# meaningless, and this is the same line the current voice was chosen on, so the
# comparison is direct.
TEXT = "诶，你又来啦，我还以为你把我忘了呢。"

# The three complaints, in the order the user ranked them:
#   1. 语速匀速没起伏   2. 句尾总是降调   3. 字正腔圆不吞音
# plus the standing requirement: 动漫感, NOT a realistic adult woman.
# Each description attacks a different subset so we can see which one the model
# can actually hear.
DESIGNS = [
    ("A_chatty", "十七岁的动漫少女，声音清亮偏细。说话像在跟朋友聊天，语速有快有慢，"
                 "句尾常常上扬，带一点撒娇的语气。"),
    ("B_lively", "活泼的高中女生，语气夸张、起伏很大，说话偏快，喜欢拖长音，"
                 "句尾明显上扬，偶尔带一点笑意。"),
    ("C_slur", "慵懒随意的年轻女孩，说话含糊，有吞音和连读，不字正腔圆，"
               "语速忽快忽慢，声音偏细偏高。"),
    ("D_anime", "二次元动漫少女，声音又尖又甜，像日本声优配的中文，"
                "语调夸张、起伏大，尾音上扬。"),
    ("E_plain", "年轻女性，声音自然。"),   # control: what does no direction give?
]

from qwen_tts import Qwen3TTSModel  # noqa: E402

print("loading", MODEL, flush=True)
t0 = time.time()
model = Qwen3TTSModel.from_pretrained(MODEL, device_map="cpu",
                                      dtype=torch.float32)
print(f"loaded in {time.time()-t0:.0f}s\n", flush=True)

for name, instruct in DESIGNS:
    t = time.time()
    try:
        wavs, sr = model.generate_voice_design(
            text=TEXT, language="Chinese", instruct=instruct)
    except Exception as e:
        print(f"{name:10} FAILED: {type(e).__name__}: {e}", flush=True)
        continue
    wav = np.asarray(wavs[0], dtype=np.float32)
    path = os.path.join(OUT, name + ".wav")
    sf.write(path, wav, sr, subtype="PCM_16")
    print(f"{name:10} {len(wav)/sr:5.2f}s  sr={sr}  {time.time()-t:5.1f}s  -> {path}",
          flush=True)

print("\nin", OUT)
