"""Validate the local VTuber stack without starting the web server.

Checks, in order:
  1. conf.yaml parses and passes the project's own pydantic validation
  2. the Qwen3-TTS engine really produces a wav, and how long it takes
  3. the OpenAI-compatible LLM endpoint answers

Run from the project root with the project venv:
    .venv/Scripts/python.exe validate_local_stack.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="INFO")

FAIL = []


def step(name):
    print("\n" + "=" * 60)
    print(name)
    print("=" * 60)


# ---------------------------------------------------------------- 1. config
step("1. config validation")
try:
    from src.open_llm_vtuber.config_manager import Config, read_yaml, validate_config

    raw = read_yaml("conf.yaml")
    cfg = validate_config(raw)
    print("conf_version :", cfg.system_config.conf_version)
    print("llm provider :", cfg.character_config.agent_config.agent_settings
          .basic_memory_agent.llm_provider)
    print("tts_model    :", cfg.character_config.tts_config.tts_model)
    print("asr_model    :", cfg.character_config.asr_config.asr_model)
    tts_cfg = cfg.character_config.tts_config
    q = getattr(tts_cfg, tts_cfg.tts_model.lower())
    print("qwen3_tts    :", q.model_dump())
except Exception as e:
    FAIL.append(("config", e))
    print("CONFIG FAILED:", type(e).__name__, e)
    raise SystemExit(1)

# ---------------------------------------------------------------- 2. TTS
step("2. Qwen3-TTS engine")
try:
    from src.open_llm_vtuber.tts.tts_factory import TTSFactory

    engine = TTSFactory.get_tts_engine(
        tts_cfg.tts_model, **q.model_dump()
    )
    for text in ["你好，我是本地运行的虚拟主播。", "今天的天气真不错。"]:
        t0 = time.time()
        path = engine.generate_audio(text)
        dt = time.time() - t0
        size = os.path.getsize(path) if os.path.exists(path) else 0
        print("  %-24s -> %s  %.1f KB  in %.2f s"
              % (text[:20], path, size / 1024, dt))
        if size < 1000:
            FAIL.append(("tts", "output too small: %s" % path))
except Exception as e:
    FAIL.append(("tts", e))
    print("TTS FAILED:", type(e).__name__, e)

# ---------------------------------------------------------------- 3. LLM
step("3. llama-server OpenAI endpoint")
try:
    import httpx

    base = raw["character_config"]["agent_config"]["llm_configs"][
        "openai_compatible_llm"]["base_url"]
    base = base.replace("/v1", "")
    r = httpx.get(base + "/health", timeout=5.0)
    print("health:", r.status_code, r.text[:120])

    r = httpx.post(
        base + "/v1/chat/completions",
        json={
            "model": "qwen-local",
            "messages": [{"role": "user", "content": "用一句话打招呼"}],
            "max_tokens": 60,
            "stream": False,
        },
        timeout=90.0,
    )
    data = r.json()
    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""
    print("reply content   :", repr(content[:120]))
    print("reply reasoning :", repr(reasoning[:80]))
    print("usage           :", data.get("usage"))
    if not content and not reasoning:
        FAIL.append(("llm", "empty reply (both content and reasoning blank)"))
except Exception as e:
    FAIL.append(("llm", e))
    print("LLM FAILED:", type(e).__name__, e)

# ---------------------------------------------------------------- summary
step("SUMMARY")
if FAIL:
    for k, e in FAIL:
        print("FAIL %-8s %s" % (k, e))
    sys.exit(1)
print("all checks passed")
