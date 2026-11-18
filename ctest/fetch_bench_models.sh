#!/usr/bin/env bash
# 重建基准测试用的 GGUF（§1–§4）。
#
# 为什么需要这个脚本：benchmark_results.md 的 §1–§4 用的是**本地从 HF 原始权重
# 转换 + 量化**出来的文件，不是任何现成的预量化 GGUF。所以"重新下载"不等于
# "恢复复现"——必须走同一条管线：modelscope 原始权重 -> convert_hf_to_gguf.py
# -> llama-quantize。这条链跑出来的张量负载与 2026-09 那批一致（尺寸对齐到
# 0.01 MiB），速度差异才归因得到编译器/机器，而不是"换了个模型文件"。
#
# 用法：
#   bash ctest/fetch_bench_models.sh            # 缺什么补什么
#   bash ctest/fetch_bench_models.sh qwen0.6b   # 只做这一组
#   FORCE=1 bash ctest/fetch_bench_models.sh    # 已有也重做
#
# 源站用 ModelScope：huggingface.co 在本机不可达（curl 直接 000）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLAMA_DIR="${LLAMA_DIR:-$ROOT/../cpu-afterburner/llama.cpp}"
PY="${PY:-$ROOT/.venv/Scripts/python.exe}"
M="${M:-$ROOT/models}"
Q="$LLAMA_DIR/build/bin/llama-quantize.exe"
CONV="$LLAMA_DIR/convert_hf_to_gguf.py"
MS="https://modelscope.cn/models"
ONLY="${1:-}"

[ -x "$PY" ]      || { echo "NO_PYTHON: $PY" >&2; exit 1; }
[ -f "$CONV" ]    || { echo "NO_CONVERTER: $CONV" >&2; exit 1; }
[ -x "$Q" ]       || { echo "NO_QUANTIZE: $Q（先跑 ctest/build_llama.bat）" >&2; exit 1; }
mkdir -p "$M"

# 期望的张量负载（MiB）= 载入后所有 tensor 的 n_bytes 之和，与 benchmark_results.md
# 记的"模型大小"同一口径。对不上就说明拿到了不同的东西，宁可报错也别测。
fetch_src() {                     # fetch_src <repo> <dest-dir> <file...>
    local repo="$1" dest="$2"; shift 2
    mkdir -p "$dest"
    for f in "$@"; do
        if [ -s "$dest/$f" ] && [ "${FORCE:-0}" != "1" ]; then continue; fi
        echo "  dl $repo/$f"
        curl -sL -C - -m 3600 -o "$dest/$f" "$MS/$repo/resolve/master/$f" \
            || { echo "DOWNLOAD_FAILED: $f" >&2; exit 1; }
    done
}

convert_src() {                   # convert_src <src-dir> <out-f16>
    local src="$1" out="$2"
    if [ -s "$out" ] && [ "${FORCE:-0}" != "1" ]; then return; fi
    echo "  convert -> $(basename "$out")"
    "$PY" "$CONV" "$src" --outtype f16 --outfile "$out" >/dev/null 2>&1 \
        || { echo "CONVERT_FAILED: $src" >&2; exit 1; }
}

quantize() {                      # quantize <f16> <out> <type> <expect-mib>
    local f16="$1" out="$2" type="$3" expect="$4"
    if [ -s "$out" ] && [ "${FORCE:-0}" != "1" ]; then
        echo "  have $(basename "$out")"
    else
        echo "  quantize $type -> $(basename "$out")"
        "$Q" "$f16" "$out" "$type" 16 >/dev/null 2>&1 \
            || { echo "QUANTIZE_FAILED: $out" >&2; exit 1; }
    fi
    # 张量负载校验：比文件大小更严（文件大小含元数据/对齐，会随 converter 变）
    "$PY" - "$out" "$expect" <<'PY'
import sys, gguf
path, expect = sys.argv[1], float(sys.argv[2])
got = sum(t.n_bytes for t in gguf.GGUFReader(path).tensors) / 1048576
tag = "ok " if abs(got - expect) < 0.05 else "MISMATCH"
print("    %s %-30s %8.2f MiB (want %.2f)" % (tag, path.split("/")[-1].split("\\")[-1], got, expect))
sys.exit(0 if tag == "ok " else 1)
PY
}

do_qwen06b() {
    local d="$M/Qwen3-0.6B-src" f16="$M/Qwen3-0.6B-f16.gguf"
    echo "[qwen0.6b]"
    fetch_src Qwen/Qwen3-0.6B "$d" config.json generation_config.json \
        tokenizer.json tokenizer_config.json vocab.json merges.txt model.safetensors
    convert_src "$d" "$f16"
    quantize "$f16" "$M/qwen0.6b-q2_k.gguf"   Q2_K  325.52
    quantize "$f16" "$M/qwen0.6b-q3_k_l.gguf" Q3_K_L 409.50
    quantize "$f16" "$M/qwen0.6b-q4_k_m.gguf" Q4_K_M 456.11
    quantize "$f16" "$M/qwen0.6b-q8_0.gguf"   Q8_0  761.80
}

do_qwen4b() {
    local d="$M/Qwen3-4B-Base-src" f16="$M/Qwen3-4B-Base-f16.gguf"
    echo "[qwen3-4b-base]"
    fetch_src Qwen/Qwen3-4B-Base "$d" config.json generation_config.json \
        tokenizer.json tokenizer_config.json vocab.json merges.txt \
        model.safetensors.index.json \
        model-00001-of-00003.safetensors model-00002-of-00003.safetensors \
        model-00003-of-00003.safetensors
    convert_src "$d" "$f16"
    quantize "$f16" "$M/Qwen3-4B-Base-Q4_K_M.gguf" Q4_K_M 2375.91
}

do_glm4b() {
    local d="$M/glm-edge-4b-src" f16="$M/glm-edge-4b-f16.gguf"
    echo "[glm-edge-4b-chat]"
    fetch_src ZhipuAI/glm-edge-4b-chat "$d" config.json generation_config.json \
        tokenizer.json tokenizer_config.json tokenizer.model \
        model.safetensors.index.json \
        model-00001-of-00002.safetensors model-00002-of-00002.safetensors
    convert_src "$d" "$f16"
    quantize "$f16" "$M/glm-edge-4b-q4_k_m.gguf" Q4_K_M 2502.64
}

case "$ONLY" in
    "")              do_qwen06b; do_qwen4b; do_glm4b ;;
    qwen0.6b|0.6b)   do_qwen06b ;;
    qwen4b|4b)       do_qwen4b ;;
    glm4b|glm)       do_glm4b ;;
    *) echo "unknown target: $ONLY (qwen0.6b | qwen4b | glm4b)" >&2; exit 2 ;;
esac
echo "DONE. src 目录（models/*-src）可留也可删，删了下次要重新下载。"
