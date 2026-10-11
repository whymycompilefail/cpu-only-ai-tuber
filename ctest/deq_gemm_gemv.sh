#!/bin/bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Discriminating experiment: kernel-bound or GEMV-shape-bound?
#
#   Same quant type, two very different kernels:
#     prefill = GEMM, COMPUTE-bound, weights reused across n_prompt tokens
#     decode  = GEMV, BANDWIDTH-bound, weights read once per token
#
#   So the two need DIFFERENT normalisations (getting this wrong is why this script
#   was rewritten once):
#     decode efficiency = (ts / ts_f16) / (size_f16 / size)   ideal 1.0, bytes are the
#                         only thing that should matter for a bandwidth-bound kernel
#     prefill efficiency = ts / ts_f16                        ideal 1.0, same FLOPs,
#                         so anything below 1.0 is pure dequantization overhead
#
#   Read-out:
#     decode bad + prefill fine  -> kernel is OK, the GEMV SHAPE is the problem
#     both bad                   -> the quant kernel itself is the problem
#
#   Also runs a 4B pair: if the "access granularity" hypothesis holds (a GEMV row is
#   K * bytes_per_elem; smaller quant => shorter rows => worse DRAM efficiency), then
#   the 4B model, whose K is 2.5x larger, must show a HIGHER decode efficiency.
#
#   Serial, zero concurrency.
#
# Usage: bash ctest/deq_gemm_gemv.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
B=$ROOT/llama.cpp/build/bin/llama-bench.exe
D=$ROOT/models
cd "$HERE"

python - "$B" "$D" <<'PY'
import json, subprocess, sys
B, D = sys.argv[1], sys.argv[2]

GROUPS = [
    ("0.6B", ["Qwen3-0.6B-f16", "Qwen3-0.6B-q8_0", "Qwen3-0.6B-q4_k_m",
              "qwen0.6b-q3_k_l", "qwen0.6b-q2_k"]),
    ("4B",   ["qwen3-4b-f16", "qwen3-4b-q4_k_m"]),
]

def bench(m, pp=512, tg=128, t=12):
    out = subprocess.run([B, "-m", "%s/%s.gguf" % (D, m), "-p", str(pp), "-n", str(tg),
                          "-t", str(t), "-fa", "0", "-r", "1", "-o", "jsonl"],
                         capture_output=True, text=True).stdout
    rows = [json.loads(l) for l in out.splitlines() if l.strip().startswith("{")]
    res = {}
    for r in rows:
        if r["n_prompt"] > 0 and r["n_gen"] == 0: res["pp"] = r
        if r["n_prompt"] == 0 and r["n_gen"] > 0: res["tg"] = r
    return res

for gname, models in GROUPS:
    print("=== %s ===" % gname)
    data = {}
    for m in models:
        r = bench(m)
        if "pp" not in r or "tg" not in r:
            print("  %-18s FAILED" % m); continue
        data[m] = r
        print("  %-18s %8.1f MB   pp512=%8.1f t/s   tg128=%7.2f t/s"
              % (m, r["tg"]["model_size"]/1048576, r["pp"]["avg_ts"], r["tg"]["avg_ts"]))

    if not data: continue
    ref_name = models[0]
    if ref_name not in data: continue
    ref = data[ref_name]
    sz_ref = ref["tg"]["model_size"]
    print()
    print("  %-18s %10s %10s   (%s = 100%% reference)" % ("model", "tg_eff", "pp_eff", ref_name))
    for m in models:
        if m not in data: continue
        sz = data[m]["tg"]["model_size"]
        tg_eff = (data[m]["tg"]["avg_ts"] / ref["tg"]["avg_ts"]) / (sz_ref / sz)
        pp_eff = data[m]["pp"]["avg_ts"] / ref["pp"]["avg_ts"]
        print("  %-18s %9.1f%% %9.1f%%" % (m, 100*tg_eff, 100*pp_eff))
    print()
    print("  tg_eff = decode bandwidth efficiency  (ideal 100% = speed scales as 1/bytes)")
    print("  pp_eff = prefill compute efficiency   (ideal 100% = same FLOPs, no dequant cost)")
    print()
PY
