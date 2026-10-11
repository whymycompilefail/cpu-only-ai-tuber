"""Is a 'too long' clip actual speech, trailing silence, or a TTS loop?

Splits a wav into 0.5s frames and reports per-frame RMS, so we can tell
whether the model kept generating after the sentence was spoken.
"""
import struct
import sys
import wave


def frames(path):
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(n)
    if w.getsampwidth() != 2:
        return None
    data = struct.unpack("<%dh" % (len(raw) // 2), raw)
    if ch > 1:
        data = data[::ch]
    return data, sr


def main():
    for path in sys.argv[1:]:
        got = frames(path)
        if got is None:
            print(f"{path}: unsupported sample width")
            continue
        data, sr = got
        win = int(sr * 0.5)
        total = len(data) / sr
        print(f"\n{path.split('/')[-1]}  duration={total:.2f}s")
        peak = max(abs(v) for v in data) or 1
        rows = []
        for i in range(0, len(data), win):
            seg = data[i:i + win]
            if not seg:
                break
            rms = (sum(v * v for v in seg) / len(seg)) ** 0.5
            rows.append((i / sr, rms / peak))
        bar_max = 40
        for t, lvl in rows:
            bar = "#" * int(lvl * bar_max)
            print(f"  {t:5.1f}s {lvl:5.3f} {bar}")
        tail = rows[-3:] if len(rows) >= 3 else rows
        quiet = sum(1 for _, lvl in tail if lvl < 0.02)
        if quiet == len(tail):
            print("  -> tail frames are silent: generation overran the text")


if __name__ == "__main__":
    main()
