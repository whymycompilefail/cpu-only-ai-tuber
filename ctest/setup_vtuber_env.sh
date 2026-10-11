#!/usr/bin/env bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root, derived from this file
# Build a dedicated venv for Open-LLM-VTuber on CPU-only torch.
# Run from anywhere; all paths absolute.
set -u

PROJ="$ROOT/Open-LLM-VTuber"
export UV_CACHE_DIR="$ROOT/.uvcache"
export UV_TORCH_BACKEND=cpu

echo "=== proxy env ==="
env | grep -iE "proxy" || echo "(none)"

cd "$PROJ" || exit 1

echo "=== 1. create venv (python 3.12) ==="
uv venv --python 3.12 .venv 2>&1 | tail -5
echo "VENV_RC=$?"
ls -la .venv/Scripts/python.exe

echo "=== 2. install torch (CPU backend) first ==="
VIRTUAL_ENV="$PROJ/.venv" uv pip install --torch-backend cpu "torch>=2.6.0" 2>&1 | tail -20
echo "TORCH_RC=$?"

echo "=== 3. install rest of requirements (CPU torch backend) ==="
VIRTUAL_ENV="$PROJ/.venv" uv pip install --torch-backend cpu -r requirements.txt 2>&1 | tail -40
echo "REST_RC=$?"

echo "=== 4. verify key imports ==="
.venv/Scripts/python.exe - <<'EOF'
import importlib
mods = ["numpy", "torch", "fastapi", "uvicorn", "loguru", "pysbd",
        "soundfile", "sherpa_onnx", "onnxruntime", "openai", "httpx",
        "ruamel.yaml", "websockets", "scipy"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, "__version__", "?")
        print("OK   %-14s %s" % (m, v))
    except Exception as e:
        print("FAIL %-14s %s" % (m, e))
import torch
print("torch cuda available:", torch.cuda.is_available())
EOF
echo "VERIFY_RC=$?"

echo "=== 5. venv size ==="
du -sh .venv 2>/dev/null
