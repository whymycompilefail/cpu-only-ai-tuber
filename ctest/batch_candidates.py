#!/usr/bin/env python
"""Generate a grid of voices and score them against the three complaints.

Cloning turned out not to inherit anything predictable (see the note in
ctest/clone_from_design.py), so designing one voice is pointless. What we CAN do
is generate a lot of candidates and pick a good one -- the diversity is real even
though the mapping from reference to output is not controllable.

Scoring is aimed at the three things the user actually complained about:

  1. 语速匀速没起伏  -> pitch dynamics. A flat line is the sound of reading.
     Measured as the std-dev of the F0 contour, plus its p90-p10 spread.
  2. 句尾总是降调    -> ending contour. Compare the F0 of the last 20% of the
     utterance against the middle; positive means she lifts at the end.
  3. 字正腔圆不吞音  -> NOT scored here. We proved pronunciation does not come
     from the reference at all, so no candidate can win on this axis. Pretending
     otherwise would just be measuring noise.

Plus a soft preference on pitch height: the chosen-so-far voice is 311 Hz and
reads as an adult woman, so aim higher without going shrill.

usage:
  Open-LLM-VTuber/.venv/Scripts/python.exe ctest/batch_candidates.py [TEXT] [OUTDIR]
"""
import glob
import json
import os
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import librosa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "llama.cpp", "build", "bin", "llama-tts.exe")
M = os.path.join(ROOT, "models", "Qwen3-TTS-0.6B-q8_0.gguf")
MM = os.path.join(ROOT, "models", "mmproj-Qwen3-TTS-0.6B-q8_0.gguf")
DEFAULT_TEXT = "诶，你又来啦，我还以为你把我忘了呢。"
TEXT = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT
OUT = os.path.join(ROOT, "ctest", "voice_ab",
                   sys.argv[2] if len(sys.argv) > 2 else "batch")
os.makedirs(OUT, exist_ok=True)

# The five designed voices plus the one already running. Six seeds each: seed
# randomness turned out to be the dominant effect (79 Hz spread from seed alone),
# so sampling seeds is where the diversity actually comes from.
REFS = sorted(glob.glob(os.path.join(ROOT, "ctest", "voice_ab", "voicedesign", "*.wav")))
REFS += [os.path.join(ROOT, "models", "speaker_refs", "kokoro_zf_xiaoyi.wav")]
SEEDS = [1, 2, 3, 4, 5, 6]


def contour(path):
    y, sr = librosa.load(path, sr=None)
    f, v, _ = librosa.pyin(y, fmin=80, fmax=600, sr=sr, frame_length=1024)
    f = f[v]
    f = f[~np.isnan(f)]
    if len(f) < 10:
        return None
    mid = f[int(len(f) * .2):int(len(f) * .8)]
    tail = f[int(len(f) * .8):]
    return dict(
        dur=len(y) / sr,
        f0=float(np.median(f)),
        std=float(np.std(f)),
        spread=float(np.percentile(f, 90) - np.percentile(f, 10)),
        # positive = she lifts at the end of the sentence
        lift=float(np.mean(tail) - np.mean(mid)),
    )


rows = []
for ref in REFS:
    rname = os.path.basename(ref)[:-4]
    for s in SEEDS:
        name = f"{rname}__s{s}"
        dest = os.path.join(OUT, name + ".wav")
        if not os.path.exists(dest):
            subprocess.run([BIN, "-m", M, "-mm", MM, "--tts-lang", "zh", "-t", "12",
                            "-n", "96", "-s", str(s), "--tts-speaker-file", ref,
                            "-o", dest, "-p", TEXT],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not os.path.exists(dest):
            continue
        c = contour(dest)
        if c is None:
            continue
        c.update(name=name, ref=rname, seed=s)
        rows.append(c)
        print(f"  {name:24} {c['dur']:5.2f}s {c['f0']:6.0f}Hz "
              f"std{c['std']:5.1f} lift{c['lift']:+6.1f}", flush=True)

# --- scoring -------------------------------------------------------------
# height: peak preference around 370 Hz, the current voice is 311 and reads adult
def clamp(x):
    return max(0.0, min(1.0, x))


for c in rows:
    c["s_height"] = clamp(1 - abs(c["f0"] - 370) / 90)
    c["s_dyn"] = clamp(c["std"] / 45)
    c["s_lift"] = clamp(c["lift"] / 40 + 0.5)
    c["score"] = .35 * c["s_height"] + .40 * c["s_dyn"] + .25 * c["s_lift"]

rows.sort(key=lambda c: -c["score"])
print(f"\n{len(rows)} candidates. top 8:\n")
print(f"{'name':26}{'时长':>6}{'F0':>7}{'起伏':>7}{'句尾':>8}{'总分':>7}")
for c in rows[:8]:
    print(f"{c['name']:26}{c['dur']:6.2f}{c['f0']:7.0f}{c['std']:7.1f}"
          f"{c['lift']:+8.1f}{c['score']:7.3f}")

# baseline: what is running in the stack right now (ref kokoro_zf_xiaoyi, seed 1)
base = [c for c in rows if c["name"] == "kokoro_zf_xiaoyi__s1"]
if base:
    b = base[0]
    print(f"\n[基准] 当前在栈里跑的 kokoro_zf_xiaoyi__s1: "
          f"{b['dur']:.2f}s {b['f0']:.0f}Hz std{b['std']:.1f} "
          f"lift{b['lift']:+.1f} score{b['score']:.3f}")

with open(os.path.join(OUT, "scores.json"), "w") as fh:
    json.dump(rows, fh, indent=1)
print("\nall scored in", os.path.join(OUT, "scores.json"))
