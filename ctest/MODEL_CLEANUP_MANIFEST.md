# 模型 + 孤儿脚本 清理清单

> 生成时间：2026-10-17
> 范围：`models/` 下多余模型 + 引用它们的 `ctest/` 旧脚本
> 状态：**已执行（2026-10-17）**。模型永久删除 ≈22.1 GB（8 项）+ 死脚本删除 33 个（24 .sh + 4 .py + np_batch.sh + 4 个 q2_k 脚本）；扫描器死字符串已清理（cleanup_purge/cleanup_scan/scrub_scan 各 2 处）。详见对话记录。

---

## 一、磁盘上仍存在、待删除的模型（之前已讨论）

| 模型文件 | 大小 | 是否在用 | 引用它的本脚本 |
|---|---|---|---|
| `qwen3-4b-base/`（目录） | 7.6 G | 否 | 无（纯下载残留） |
| `qwen3-4b-f16.gguf` | 7.5 G | 否 | `deq_gemm_gemv.sh:40` |
| `qwen3-4b-rp-q4_k_m.gguf` | 2.4 G | 否 | 无（纯残留） |
| `qwen3-4b-q4_k_m.gguf` | 2.4 G | 否 | 见下表 B 组 |
| `Qwen3.5-0.8B-f16.gguf` | 1.5 G | 否 | 无运行引用（仅扫描器字符串 + 文档） |
| `qwen0.6b-q3_k_l.gguf` | 416 M | 否 | `deq_ab2.sh:23`、`deq_scaling.sh:30`、`deq_gemm_gemv.sh:39` |
| `mmproj-Qwen3-TTS-0.6B-q5_0.gguf` | 260 M | 否 | 无（f16/q8_0 两个 mmproj 已够） |

**合计待回收：≈ 22.0 G**（7.6+7.5+2.4+2.4+1.5+0.416+0.260）

> 必留的活跃 TTS 资产（**不要动**）：`Qwen3-TTS-0.6B-f16.gguf`、`Qwen3-TTS-0.6B-q8_0.gguf`、`mmproj-Qwen3-TTS-0.6B-f16.gguf`、`mmproj-Qwen3-TTS-0.6B-q8_0.gguf`、`kokoro/`、`speaker_refs/`。
> 活跃 LLM 栈在 `Open-LLM-VTuber/models/`，不在此目录；`ctest/models/` 全部是早期实验残留。

---

## 二、引用"待删模型"的本项目脚本（删模型后会失效，应一并清）

### 2.1 `qwen3-4b-q4_k_m.gguf`（待删，被实验脚本引用）
- `ctest/np_batch.sh:9`
- `ctest/verify_fa_gqa.sh:27`
- `ctest/draft_ab.sh:11`
- `ctest/draft_scan.sh:7`
- `ctest/phase_timing.sh:10,25`
- `ctest/retest_4b.sh:7`
- `ctest/retest_spec.sh:7`
- `ctest/selfcheck.sh:9,10`
- `ctest/self_ab.sh:7`
- `ctest/deq_gemm_gemv.sh:40`（同时引用 qwen3-4b-f16）

### 2.2 `qwen0.6b-q3_k_l.gguf`（待删）
- `ctest/deq_ab2.sh:23`
- `ctest/deq_scaling.sh:30`
- `ctest/deq_gemm_gemv.sh:39`

### 2.3 `Qwen3.5-0.8B-f16.gguf`（待删，无脚本运行引用）
仅被扫描器当作匹配字符串，不直接 `-m` 加载：
- `ctest/cleanup_purge.py:30`
- `ctest/cleanup_scan.py:37`
- `ctest/scrub_scan.py:82`
- 文档提及：`ctest/benchmark_model_choice.md`、`ctest/benchmark_results.md`

> `qwen3-4b-base/`、`qwen3-4b-rp-q4_k_m.gguf`、`mmproj-Qwen3-TTS-0.6B-q5_0.gguf` 无任何脚本引用，是纯残留，删之无副作用。

---

## 三、引用"已删除 Qwen3-0.6B"的死脚本（模型早没了，现在跑必失败）

**这是"顺带清旧脚本"的主目标**——这些脚本指向的 `Qwen3-0.6B-{f16,q5_0,q4_k_m,q8_0,q6_K,q5_K,q4_0}` 全部已从 `models/` 移除，但它们从未被清理。

### 3.1 shell（`.sh`）—— 直接 `-m`/`M=` 加载已删文件
| 脚本 | 引用行 | 引用的已删模型 |
|---|---|---|
| `kv_cache_reuse_test.sh` | 26 | Qwen3-0.6B-f16 |
| `kv_layout_test.sh` | 33 | Qwen3-0.6B-f16 |
| `kv_reuse_turns.sh` | 19 | Qwen3-0.6B-f16 |
| `restart_all.sh` | 7 | Qwen3-0.6B-q5_0 |
| `spec_ab.sh` | 8 | Qwen3-0.6B-q4_k_m |
| `ttft_persist.sh` | 23 | Qwen3-0.6B-f16 |
| `ttft_server.sh` | 18 | Qwen3-0.6B-f16 |
| `ttft_server2.sh` | 16 | Qwen3-0.6B-f16 |
| `ttft_stream.sh` | 18 | Qwen3-0.6B-f16 |
| `validate_stack.sh` | 9 | Qwen3-0.6B-q5_0 |
| `verify_fixes.sh` | 15 | Qwen3-0.6B-q5_0 |
| `verify_fa_gqa.sh` | 23,24,36 | Qwen3-0.6B-f16 |
| `verify_spec03.sh` | 36,77,93 | Qwen3-0.6B-f16 |
| `draft_ab.sh` | 12,54 | Qwen3-0.6B-q4_k_m |
| `draft_scan.sh` | 8 | Qwen3-0.6B-q4_k_m |
| `phase_timing.sh` | 25 | Qwen3-0.6B-q4_k_m |
| `retest_4b.sh` | 8 | Qwen3-0.6B-q4_k_m |
| `retest_spec.sh` | 8 | Qwen3-0.6B-q4_k_m |
| `selfcheck.sh` | 9,10 | Qwen3-0.6B-q4_k_m |
| `self_ab.sh` | 3,7 | Qwen3-0.6B-q4_k_m |
| `deq_ab.sh` | 24 | Qwen3-0.6B 系列（全删） |
| `deq_ab2.sh` | 23,24 | Qwen3-0.6B 系列 + qwen0.6b-q3_k_l + qwen0.6b-q2_k |
| `deq_scaling.sh` | 30 | Qwen3-0.6B 系列 + qwen0.6b-q2_k + qwen0.6b-q3_k_l |
| `deq_gemm_gemv.sh` | 38,39,40 | Qwen3-0.6B 系列 + qwen0.6b-q3_k_l + qwen0.6b-q2_k + qwen3-4b-f16 + qwen3-4b-q4_k_m |

### 3.2 python（`.py`）—— 引用已删模型
- `ctest/ab_ratio.py:20,44,82-87`（`F16='Qwen3-0.6B-f16'`、`'Qwen3-0.6B-q4_k_m'`）
- `ctest/probe_hit.py:398`（`default=ROOT + "/Qwen3-0.6B"`，目录已删）
- `ctest/gguf_types.py:8`（usage 示例 `models/Qwen3-0.6B-q4_0.gguf`）
- `ctest/fa_alpha.py:2,5,20,21`（字符串提及，非运行引用）

### 3.3 文档（文本提及，非脚本）
- `ctest/benchmark_model_choice.md`、`ctest/benchmark_results.md` —— **保留**。它们是项目测量/选型方法论基石，被 `README.md`（4 处）、`specs/` 下 5 个 spec、`patches/llama-cpp-cpu-tuning.patch`（8+ 处注释）、`ASSETS.md`、`ctest/run_stack.sh` 广泛引用为证据链（如"非带宽受限"、量化 V 禁令根因、带宽墙常数均出自此处）。含已删模型名仅为历史记录，不影响运行。**2026-10-17 用户拍板保留**。
- `specs/fa-auto-adaptive.md`、`specs/prompt-ledger.md`、`specs/legacy-quant-v-op.md`、`specs/fa-gqa-loop-reorder.md` —— 独立 spec 文档，保留（它们是引用方，不是被清对象）。

---

## 四、清理器里的死字符串（删模型后顺手清）

这些不是运行引用，是隐私扫描/清理配置里的匹配项，模型已删或待删后匹配不到：
- `ctest/cleanup_purge.py:30-31`（`Qwen3.5-0.8B/.git`、`Qwen3-0.6B/.git`）
- `ctest/cleanup_scan.py:34,37`（同上）
- `ctest/scrub_scan.py:81-82`（`Qwen3-0.6B`、`Qwen3.5-0.8B`）

---

## 五、非活跃但存活、可选清理（坏文件 / 实验遗留）

| 文件 | 大小 | 状态 | 引用它的脚本 |
|---|---|---|---|
| `qwen0.6b-q2_k.gguf` | 332 M | **坏转换**（`verify_spec03.sh:74` 注释确认），非活跃 | `ctx_sweep.sh:8`、`fa_adaptive.sh:8`、`perf_fa_gqa.sh:19`、`perf_spec03.sh:14,33-38`、`verify_fa_gqa.sh:25,26,28`、`verify_spec03.sh:33-38`、`deq_ab2.sh`、`deq_scaling.sh`、`deq_gemm_gemv.sh` |

> 若决定删除 `qwen0.6b-q2_k.gguf`，这组脚本需同步改或删。活跃栈在 `Open-LLM-VTuber/models`，此文件不参与推流。

---

## 六、明确不要动的东西（grep 命中但非本项目旧脚本）

- `llama.cpp/` 源码树：`ci/run.sh`、`README.md`、`docs/*`、`tools/**/tests.sh`、`tools/server/tests/*` 里的 `Qwen3-0.6B/0.8B/4B` 是 HuggingFace **repo 路径**，第三方代码，勿改。
- `Open-LLM-VTuber/` 源码：`tts.py:76`、`config_manager/tts.py:700` 默认引用 `mmproj-Qwen3-TTS-0.6B-q8_0.gguf` —— 这是**活跃 TTS 栈必留**的 mmproj。
- `MiniCPM5-1B-GGUF/README*.md` —— 第三方模型 README。
- `specs/` 设计文档 —— 历史记录，保留。

---

## 七、建议执行顺序（待拍板后）

1. **先删死脚本（第三节）**：它们引用的模型早已不在，删之零功能损失。
2. **再删待删模型（第一节）**，同时删第二节里"只服务这些模型"的脚本（如 `np_batch.sh`、`draft_*.sh`、`retest_*.sh`、`selfcheck.sh`、`self_ab.sh` 等纯实验脚本）。
3. **清理第四节的扫描器死字符串**。
4. **`qwen0.6b-q2_k.gguf`（第五节）** 作为 B 类可选：确认不再做 0.6B 量化对比后再删，并同步改 9 个脚本。
5. 所有删除走回收站机制，删前再列最终文件清单过目；不擅自动 `llama.cpp/`、`Open-LLM-VTuber/`、活跃 TTS 资产。

---

## 八、历史产物最终清查（2026-10-17 续）

用户要求"把历史产物也删了"。全量 grep `ctest/` 含已删模型名（`qwen3-4b|Qwen3.5-0.8B|qwen0.6b|Qwen3-0.6B|mmproj-Qwen3-TTS-0.6B-q5_0`）的结果：

- 命中仅 3 个文件：`benchmark_model_choice.md`、`benchmark_results.md`、`MODEL_CLEANUP_MANIFEST.md`（本清单，保留）。
- 此前提及的 `*.log/*.json/*.txt` 在真实磁盘已不含这些名字（无残留）。
- `repair_eval/` 零命中（那批微调实验结果独立保留）。

结论：`ctest/` 下已无可清的"含已删模型名的历史产物"。仅剩的 `benchmark_*.md` 经引用核查，是被 README/specs/patch/run_stack.sh 广泛引用的核心方法论文档（非孤立垃圾），**用户拍板保留**。故历史产物清理到此为止，不再删除。
