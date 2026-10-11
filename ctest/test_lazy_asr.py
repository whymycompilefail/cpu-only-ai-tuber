"""临时验证：ASR 延迟初始化的三条行为契约。跑完即删。"""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, "Open-LLM-VTuber/src")
sys.path.insert(0, "Open-LLM-VTuber")  # `prompts` 包在这里，不在 src 下
import open_llm_vtuber.service_context as sc  # noqa: E402


class FakeASR:
    pass


def make_cfg():
    cfg = MagicMock()
    cfg.asr_model = "sherpa_onnx_asr"
    cfg.sherpa_onnx_asr = MagicMock()
    cfg.sherpa_onnx_asr.model_dump.return_value = {}
    return cfg


# --- 1. 没有 character_config 时，读 asr_engine 不应触发任何加载 ------------
sc.ASRFactory = MagicMock()
sc.ASRFactory.get_asr_system.return_value = FakeASR()
ctx = sc.ServiceContext()
assert ctx.asr_engine is None, "无配置时不应返回引擎"
n0 = sc.ASRFactory.get_asr_system.call_count
assert n0 == 0, f"不应触发加载，实际 {n0} 次"
print(f"1) 无配置 -> asr_engine={ctx.asr_engine}, 加载次数={n0}  OK")

# --- 2. 有配置时，首次读取才加载 -------------------------------------------
cfg = make_cfg()
char = MagicMock()
char.asr_config = cfg
ctx.character_config = char
engine = ctx.asr_engine
n1 = sc.ASRFactory.get_asr_system.call_count
assert engine is not None, "有配置时应返回引擎"
assert n1 == 1, f"首次读取应加载 1 次，实际 {n1}"
print(f"2) 有配置 -> 引擎={type(engine).__name__}, 加载次数={n1}  OK")

# --- 3. 再次读取走缓存，不重复加载 -----------------------------------------
for _ in range(5):
    _ = ctx.asr_engine
n2 = sc.ASRFactory.get_asr_system.call_count
assert n2 == 1, f"缓存失效，累计加载 {n2} 次"
print(f"3) 连续读 5 次 -> 累计加载次数仍为 {n2}  OK")

# --- 4. 构建失败：降级返回 None，且不会每次都重试下载 -----------------------
sc.ASRFactory.get_asr_system.side_effect = RuntimeError("weights missing / offline")
ctx2 = sc.ServiceContext()
char2 = MagicMock()
char2.asr_config = make_cfg()
ctx2.character_config = char2

before = sc.ASRFactory.get_asr_system.call_count
assert ctx2.asr_engine is None, "失败时应降级为 None（不抛异常）"
for _ in range(5):
    assert ctx2.asr_engine is None
after = sc.ASRFactory.get_asr_system.call_count
retried = after - before
assert retried == 1, f"失败后应只尝试 1 次并记住，实际 {retried} 次"
print(f"4) 加载失败 -> 降级 None 且不崩；重复读 5 次仅尝试 {retried} 次  OK")

# --- 5. 显式 init_asr 仍然可用（预热路径）----------------------------------
sc.ASRFactory.get_asr_system.side_effect = None
sc.ASRFactory.get_asr_system.return_value = FakeASR()
ctx3 = sc.ServiceContext()
char3 = MagicMock()
char3.asr_config = None
ctx3.character_config = char3
ctx3.init_asr(make_cfg())
assert ctx3.asr_engine is not None, "显式预热应产出引擎"
print(f"5) 显式 init_asr() -> {type(ctx3.asr_engine).__name__}  OK")

print("\nALL PASS")
