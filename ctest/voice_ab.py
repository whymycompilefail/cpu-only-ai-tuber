"""Compare speaker references by the pitch of what they actually produce.

Measuring the reference wav's own F0 is not enough: cloning does not have to
reproduce the reference's pitch, and it demonstrably does not always. So this
synthesises the same two sentences with each candidate speaker file and measures
the F0 of the OUTPUT, which is the only thing the audience hears.

Each candidate gets one resident llama-tts process (loop mode), so we pay model
load once per candidate rather than once per sentence.

usage: python voice_ab.py [--outdir DIR] [ref.wav ...]
       passes it through to the engine unchanged, i.e. no speaker locking.
"""
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
BIN = ROOT + "/llama.cpp/build/bin/llama-tts.exe"
BACKBONE = ROOT + "/models/Qwen3-TTS-0.6B-q8_0.gguf"
MMPROJ = ROOT + "/models/mmproj-Qwen3-TTS-0.6B-q8_0.gguf"
WROTE_RE = re.compile(r"\[\d+\] wrote (.*?)\s*$")

SENTENCES = [
    "今天天气真不错呀，我们出去玩吧。",
    "哎呀，你又逗我，我真的要生气了哦。",
]

OUTDIR = ROOT + "/ctest/voice_ab"
THREADS = 12


def run_one(speaker: str | None, tag: str) -> dict:
    """Synthesise SENTENCES with one reference, return their output wavs."""
    os.makedirs(OUTDIR, exist_ok=True)
    pipe = OUTDIR + f"/{tag}_pipe.wav"
    env = dict(os.environ)
    env["LLAMA_TTS_LOOP"] = "1"
    cmd = [BIN, "-m", BACKBONE, "-mm", MMPROJ, "--tts-lang", "zh",
           "-t", str(THREADS), "-n", "96", "-o", pipe]
    if speaker:
        cmd += ["--tts-speaker-file", speaker]
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    paths = []
    try:
        for i, text in enumerate(SENTENCES):
            proc.stdin.write(text + "\n")
            proc.stdin.flush()
            for _ in range(4096):
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("llama-tts exited")
                m = WROTE_RE.search(line)
                if m:
                    dst = f"{OUTDIR}/{tag}_{i}.wav"
                    shutil.copy(m.group(1), dst)
                    paths.append(dst)
                    break
    finally:
        try:
            proc.kill()
        except Exception:
            pass
    return {"wavs": paths, "time": time.time() - t0}


def main():
    args = sys.argv[1:]
    refs = []
    if "--outdir" in args:
        i = args.index("--outdir")
        globals()["OUTDIR"] = args[i + 1]
        args = args[:i] + args[i + 2:]
    if args:
        refs = args
    else:
        refs = sorted(str(p) for p in
                      __import__("pathlib").Path(ROOT + "/models/speaker_refs")
                      .glob("*.wav"))

    sys.path.insert(0, ROOT + "/ctest")
    from f0 import f0_median  # noqa: E402

    rows = []
    for ref in refs:
        tag = os.path.splitext(os.path.basename(ref))[0]
        if ref.lower() == "none":
            tag, ref = "noref", None
        try:
            r = run_one(ref, tag)
        except Exception as e:
            print(f"{tag:14} FAILED: {e}")
            continue
        pitches = [f0_median(p)[0] for p in r["wavs"]]
        rows.append((tag, pitches, r["time"], r["wavs"]))
        print(f"{tag:14} output F0 = " +
              " / ".join(f"{p:.1f}" for p in pitches) +
              f"   ({r['time']:.1f}s for {len(r['wavs'])} lines)")

    print()
    print(f"{'ref':14} {'mean F0':>9}  wavs")
    rows.sort(key=lambda r: sum(r[1]) / len(r[1]), reverse=True)
    for tag, pitches, _, wavs in rows:
        mean = sum(pitches) / len(pitches)
        print(f"{tag:14} {mean:9.1f}  " + ", ".join(wavs))


if __name__ == "__main__":
    main()
