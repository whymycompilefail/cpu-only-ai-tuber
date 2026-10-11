"""Verify the pitch shifter against synthesised tones before trusting it on speech.

Guard added after the handwritten resample+OLA version silently failed this same
test: a 220 Hz sine came back at ~270 Hz for +2, +3 and +4 semitones alike.
Run this whenever utils/pitch.py is touched.

usage: python check_pitch_shift.py
"""
import importlib.util
import os
import sys

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "pitchmod", ROOT + "/Open-LLM-VTuber/src/open_llm_vtuber/utils/pitch.py")
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

SR = 24000


def dominant_freq(y, sr=SR):
    """Peak of the magnitude spectrum for a clean single tone."""
    win = np.hanning(len(y)) * y
    spec = np.abs(np.fft.rfft(win))
    freqs = np.fft.rfftfreq(len(y), 1.0 / sr)
    return freqs[int(np.argmax(spec))]


def main():
    failed = 0
    for base in (180.0, 220.0, 294.0):
        t = np.arange(int(SR * 1.5)) / SR
        x = (0.6 * np.sin(2 * np.pi * base * t)).astype(np.float32)
        for st in (0, 1, 2, 3, 4, 5):
            y = pm.shift_semitones(x, float(st), sr=SR)
            got = dominant_freq(y)
            want = base * 2 ** (st / 12)
            err_hz = abs(got - want)
            err_cent = 1200 * np.log2(got / want) if got > 0 else float("nan")
            ok = err_hz < 8.0 and len(y) - len(x) <= SR * 0.02
            failed += 0 if ok else 1
            print(f"{'ok  ' if ok else 'FAIL'} base {base:6.1f}  +{st}  "
                  f"want {want:7.1f} Hz  got {got:7.1f} Hz  "
                  f"({err_cent:+.1f} cent)  len {len(y)}")

    # a real signal should not be turned into silence or clipping
    src = ROOT + "/ctest/voice_ab/spk_1_0.wav"
    if os.path.exists(src):
        x, sr = sf.read(src, dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        y = pm.shift_semitones(x, 3.0, sr=sr)
        ok = abs(len(y) - len(x)) <= sr * 0.02 and np.max(np.abs(y)) > 1e-3
        failed += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'} real audio: {len(x)} -> {len(y)} "
              f"samples at sr={sr}, peak={np.max(np.abs(y)):.3f}")

    print()
    print("ALL PASS" if not failed else f"{failed} CHECKS FAILED")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
