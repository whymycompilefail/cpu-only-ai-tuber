"""Estimate F0 (pitch) median of wav files -- enough to tell a male from a
female voice without listening, and to check whether a voice stays put.

Usage: python f0.py a.wav b.wav ...
"""

import sys
import wave

import numpy as np


def f0_median(path, lo=70.0, hi=400.0, step=0.020, win=0.040):
    with wave.open(path, "rb") as f:
        assert f.getnchannels() == 1, f"{path}: not mono"
        rate = f.getframerate()
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    x = data.astype(np.float64) / 32768.0
    x -= x.mean()

    win_n = int(win * rate)
    step_n = int(step * rate)
    if len(x) < win_n:
        return float("nan"), 0

    f0s = []
    for start in range(0, len(x) - win_n, step_n):
        frame = x[start:start + win_n]
        frame = frame - frame.mean()
        energy = np.sqrt(np.mean(frame ** 2))
        if energy < 0.01:          # silence frame
            continue
        frame *= np.hanning(len(frame))

        # autocorrelation via FFT
        n = 1
        while n < len(frame) * 2:
            n *= 2
        spec = np.fft.rfft(frame, n)
        acf = np.fft.irfft(spec * np.conjugate(spec), n)[:len(frame)]
        if acf[0] <= 0:
            continue

        min_lag = int(rate / hi)
        max_lag = min(int(rate / lo), len(frame) - 1)
        if max_lag <= min_lag:
            continue
        seg = acf[min_lag:max_lag]
        lag = int(np.argmax(seg)) + min_lag
        # parabolic interpolation for sub-sample precision
        if 0 < lag < len(acf) - 1:
            a, b, c = acf[lag - 1], acf[lag], acf[lag + 1]
            denom = (a - 2 * b + c)
            if denom != 0:
                lag = lag + 0.5 * (a - c) / denom
        f0 = rate / lag
        if lo <= f0 <= hi:
            f0s.append(f0)

    if not f0s:
        return float("nan"), 0
    return float(np.median(f0s)), len(f0s)


# Guard so the module can be imported by ctest/voice_ab.py without executing
# that caller's argv as filenames.
if __name__ == "__main__":
    for p in sys.argv[1:]:
        f0, n = f0_median(p)
        guess = "female" if f0 > 165 else ("male" if f0 == f0 else "?")
        print("%-34s F0 = %6.1f Hz  (%d frames)  -> %s"
              % (p.rsplit("/", 1)[-1], f0, n, guess))
