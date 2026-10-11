"""Generate candidate "young girl voice" samples side by side.

Three families, all saying the same sentence, so they can be compared by ear:
  local+0 / +2 / +3 / +4   : current local Qwen3-TTS voice, pitch-shifted here
  edge Xiaoyi (+0/+20/+40Hz): the closest "young, lively" Chinese voice in edge-tts
  edge Xiaoxiao            : included as a reference point (warm adult female)

Prints F0 and duration of each result so the choice is not made purely by ear.

usage: python voice_candidates.py [source_wav]
"""
import asyncio
import importlib.util
import os
import sys

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
PKG = ROOT + "/Open-LLM-VTuber/src"
OUT = ROOT + "/ctest/voice_ab"
TEXT = "今天天气真不错呀，我们出去玩吧，快带上我一起出门嘛。"

# load the helper without importing the whole open_llm_vtuber package __init__
spec = importlib.util.spec_from_file_location(
    "pitchmod", PKG + "/open_llm_vtuber/utils/pitch.py")
pitchmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pitchmod)

sys.path.insert(0, ROOT + "/ctest")
from f0 import f0_median  # noqa: E402


def describe(path):
    data, sr = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    f0, _ = f0_median(path)
    return f0, len(data) / sr, sr


def shift(src, dest, semitones):
    data, sr = sf.read(src, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    y = pitchmod.shift_semitones(data, semitones, sr=sr)
    # PCM_16, not soundfile's default float subtype: ctest/f0.py reads through
    # stdlib `wave`, which rejects IEEE-float wav.
    sf.write(dest, y, sr, subtype="PCM_16")
    return dest


async def edge(dest, voice, pitch):
    import edge_tts
    opt = {"pitch": pitch} if pitch else {}
    c = edge_tts.Communicate(TEXT, voice, **opt)
    await c.save(dest)


def main():
    os.makedirs(OUT, exist_ok=True)
    src = sys.argv[1] if len(sys.argv) > 1 else OUT + "/spk_1_0.wav"
    rows = []

    rows.append(("local +0 (当前)", src))
    for st in (2, 3, 4):
        p = f"{OUT}/cand_local_p{st}.wav"
        shift(src, p, float(st))
        rows.append((f"local +{st} 半音", p))

    try:
        asyncio.run(edge(f"{OUT}/cand_edge_xiaoyi.wav",
                         "zh-CN-XiaoyiNeural", None))
        rows.append(("edge Xiaoyi (少女)", f"{OUT}/cand_edge_xiaoyi.wav"))
        for hz in (20, 40):
            p = f"{OUT}/cand_edge_xiaoyi_p{hz}.wav"
            asyncio.run(edge(p, "zh-CN-XiaoyiNeural", f"+{hz}Hz"))
            rows.append((f"edge Xiaoyi +{hz}Hz", p))
        asyncio.run(edge(f"{OUT}/cand_edge_xiaoxiao.wav",
                         "zh-CN-XiaoxiaoNeural", None))
        rows.append(("edge Xiaoxiao (成年)", f"{OUT}/cand_edge_xiaoxiao.wav"))
    except Exception as e:
        print(f"[warn] edge-tts failed ({type(e).__name__}: {str(e)[:120]}) -- "
              "offline? only local candidates produced")

    print(f"{'候选':26} {'F0(Hz)':>8} {'时长(s)':>8}  {'采样率':>6}  文件")
    for name, path in rows:
        try:
            f0, dur, sr = describe(path)
        except Exception as e:
            print(f"{name:26} {'?':>8} {'?':>8}  {'?':>6}  {path}  "
                  f"({type(e).__name__})")
            continue
        print(f"{name:26} {f0:8.1f} {dur:8.2f}  {sr:>6}  {path}")


if __name__ == "__main__":
    main()
