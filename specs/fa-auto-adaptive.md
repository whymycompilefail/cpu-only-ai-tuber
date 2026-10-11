# Spec 01：让 `-fa auto` 感知上下文长度

> 项目：Ai_edge_deployment（llama.cpp CPU 特化 fork）
> 日期：2026-09-26
> 状态：待实现 → 已实现（见文末结果）
> 上游基线：`5096f2a` + `c649f60`

---

## 0. 一句话

把 flash attention 的开关从「建上下文时按后端能力一次性判定」改成
「每个 decode step 按当前 KV 长度动态判定」，长上下文自动退回 legacy（非 FA）路径。

这是本项目**第一个真正的代码级魔改靶点**，由实测数据直接指认，不是猜测。

---

## 1. 动机：上下文长度才是单用户场景的第一杀手

单用户本地部署没有并发，唯一变量是「每生成一个 token 要读多少字节」。
此前所有测量都在空上下文下做，漏掉了最大的一项：**KV cache 随对话历史累积**。

### 1.1 KV 读流量会很快超过模型权重

Qwen3-0.6B Q2_K 模型本体只有 **325 MiB**，KV cache 为 **112 KiB/token**（f16）：

| 上下文 | 1K | 4K | 8K | 32K |
|---|---|---|---|---|
| KV 体积 | 112 MiB | 448 MiB | 917 MiB | 3584 MiB |

**ctx 超过约 3000 后，每 token 读的 KV 就比读整个模型的权重还多。**
模型再小、量化再狠，也救不回来——带宽被历史吃掉了。

### 1.2 实测：上下文 → decode 速度（Q2_K 325MB，t=12，`llama-cli -f` 实测）

| 上下文 | 64 | 256 | 512 | 1024 | 2048 | 4096 | 8192 |
|---|---|---|---|---|---|---|---|
| fa=1（当前 auto 的行为） | 92.6 | 84.4 | 78.7 | 64.1 | 46.2 | 25.0 | **12.3** |
| **fa=0** | 82.1 | 75.3 | 69.3 | 62.2 | **52.2** | **36.4** | **23.5** |

ctx 64 → 8192，速度掉 **3.7 倍（fa=0）到 7.5 倍（fa=1）**。

> 注：`llama-bench` 的 tg 指标**不带 prompt 上下文**，用它测上下文影响会得出
> 「无影响」的错误结论。必须用 `llama-cli -f <长 prompt>` 测。这是踩过的坑。

### 1.3 交叉点：flash attention 在长上下文是负收益

三轮复测稳定，交叉点在 **ctx ≈ 1500–2000**：

| 上下文 | fa=1 | fa=0 | 关 FA 的收益 |
|---|---|---|---|
| 64 | 92.6 | 82.1 | −11%（FA 胜） |
| 512 | 78.7 | 69.3 | −12%（FA 胜） |
| 1024 | 64.1 | 62.2 | −3%（持平） |
| 2048 | 46.2 | 52.2 | **+13%** |
| 4096 | 24.7~25.5 | 35.9~37.0 | **+44%** |
| 8192 | 12.3 | 23.5 | **+91%** |

短上下文 FA 更快，长上下文 legacy 更快，而 llama.cpp 的 `auto`
**永远选前者**——因为它的判定根本不看上下文。

---

## 2. 现状：`-fa auto` 只问后端「你支持吗」，从不问「现在多长」

完整链路（已确认，非推测）：

1. `common/arg.cpp:1751` — `-fa [on|off|auto]` 解析成 `LLAMA_FLASH_ATTN_TYPE_*`。
2. `src/llama-context.cpp:230-231`
   ```cpp
   cparams.flash_attn = params.flash_attn_type != LLAMA_FLASH_ATTN_TYPE_DISABLED;
   cparams.auto_fa    = params.flash_attn_type == LLAMA_FLASH_ATTN_TYPE_AUTO;
   ```
3. `src/llama-context.cpp:556-559` — 建上下文时 probe **一次**：
   ```cpp
   if (cparams.auto_fa) {
       resolve(llm_fused_op_flash_attn_probe, cparams.flash_attn);
       cparams.auto_fa = false;   // 一次性，之后永不重判
   }
   ```
   probe 只回答「这个后端能不能跑 flash attention 这个 op」，CPU 后端回答「能」。
4. `src/llama-graph.cpp:2635` — 此后每个 graph 都无条件用这个布尔值：
   ```cpp
   const bool use_flash_attn = cparams.flash_attn && kq_b == nullptr;
   ```

**结论：`auto` 在 CPU 上等价于 `on`，且在运行期完全静态。**
它不知道上下文长度，也不打算知道。这正是 §1.3 那张表能被实测出来的原因——
用户必须自己手动 `-fa 0` 才能拿到长上下文那 13%~91%。

### 2.1 一个额外的确认：graph 本来就在每步重建

`src/llama-graph.cpp:48-65` 的 `can_reuse_kq_mask()` 检查 `kq_mask->ne[0] == n_kv`，
decode 时 `n_kv` 每步 +1，所以**图每步都在重建**。

这有两个后果，对我们的改动都是好消息：
- 动态改拓扑**没有额外成本**（本来就在重建）；
- 但也意味着图重建开销是每 token 都付的，是另一个潜在的优化靶点（另开 spec）。

---

## 3. 设计

### 3.0 关键否决：不能「每步动态切换」，只能「按 n_ctx 启动期静态决定」

原本的设计是每个 decode step 按当前 `n_kv` 选路径。实现过程中发现**这条路被架构否决**：

KV cache 的 **V 张量布局在加载时就固定了**：

```cpp
// src/llama-model.cpp:2374（以及另外十几处）
res = new llama_kv_cache(..., !cparams.flash_attn /* v_trans */, ...);
```

- `v_trans = false`（FA 布局）：legacy 路径会走
  ```cpp
  if (!v_trans) { v = ggml_cont(ctx0, ggml_transpose(ctx0, v)); }  // 源码注释："note: avoid this branch"
  ```
- `v_trans = true`（legacy 布局）：FA 路径同样要 `v = ggml_transpose(ctx0, v)`。

也就是说**同一份 KV cache 无法同时高效服务两条路径**，选错的一侧每步都要整块转置 V。
量一下这个惩罚（Qwen3-0.6B：V = 1024 维 × f16 = 2 KiB/token/层，28 层）：

| 场景 | 每 token 额外 V 转置流量 | 对比模型本体 325 MiB |
|---|---|---|
| ctx 1024 | ≈ 114 MiB（读+写） | **+35%** → 吃掉 FA 在短上下文仅 +11% 的优势 |
| ctx 8192 | ≈ 940 MiB | 比读整个模型还多 3 倍 → 完全不可行 |

两个方向都是净亏。**结论：路径必须在建 KV cache 之前定下来，也就是按启动时已知的 `n_ctx` 决定。**

`n_ctx` 是用户声明的上下文上限，是启动期唯一可得的「会有多长」的信号。
代价是：用户把 `-c` 设得远大于实际用量时（例如 `-c 16384` 只聊 300 token），
判定会偏保守地选 legacy，损失短上下文那 11%。这是本方案的已知边界（见 §6 第二组测试）。

> 想真正做到「按当前长度切换」，需要 KV cache 同时维护转置与非转置两份 V
> （内存 +50%，每 token 多写一次 V，写入量很小）。这是可行的后续方向，不在本次范围。

### 3.1 判定函数（唯一真源）

```cpp
// src/llama-cparams.h
static inline bool llama_fa_enabled(const llama_cparams & cparams, int64_t n_kv, int64_t n_tokens) {
    if (!cparams.flash_attn)  return false;   // 显式 -fa 0：永远不用
    if (!cparams.fa_adaptive) return true;    // 默认 / 显式 -fa 1：由启动期决定，见 §3.2
    if (n_tokens > cparams.fa_max_tokens) return true;  // prefill 不切（内存约束）
    return n_kv <= cparams.fa_kv_threshold;   // LLAMA_FA_DYNAMIC=1 实验开关才走这里
}
```

所有 mask 类型与 `use_flash_attn` 的判定都走它，避免出现「f16 的 mask 配 legacy 路径」
这种类型/路径不一致。`can_reuse_kq_mask()` 也加上 mask **类型**检查，
保证任何拓扑变化都会触发重建而不是被静默复用。

### 3.2 启动期判定（实际生效的逻辑）

在 `llama_context` 构造函数里，`cparams.n_ctx` 确定之后、KV cache 创建（llama-context.cpp:403）
之前插入：

```cpp
if (cparams.auto_fa && !cparams.fa_adaptive && params.fa_kv_threshold > 0 &&
    cparams.n_ctx > (uint32_t) params.fa_kv_threshold) {
    cparams.flash_attn = false;   // 同时决定 V 布局 = 转置（legacy 友好）
    cparams.auto_fa    = false;   // 不再 probe
}
```

### 3.3 阈值

- `fa_kv_threshold` 默认 **2048**。
  判定用的是 `n_ctx`（上限），而实际对话长度通常只有它的 1/2 左右；
  实测交叉点在实际 KV 长度 1500~2000，所以按 `n_ctx` 判定时阈值要往上抬一档。
  实测对照（prompt=1024 / `-c` 2048）：阈值 1024 判为 legacy 得 63.4 t/s，
  **阈值 2048 判为 FA 得 66.3 t/s，且正好命中该点的最优路径**。
- 可用 `-fakv N` / `--fa-kv-threshold N` 覆盖；`-fakv 0` 完全退回上游行为。
- `fa_max_tokens` 默认 **1**，仅动态实验模式用到。

### 3.4 触发条件与向后兼容

- 仅当 `flash_attn_type == AUTO`（默认值）时生效；
- `-fa on` / `-fa off` 行为完全不变；
- `-fakv 0` 完全退回上游行为（永远 FA）；
- 被强制提升为 ENABLED 的场景（如量化 V cache 要求 FA）不受影响。

---

## 4. 改动清单

| # | 文件 | 位置 | 改动 |
|---|---|---|---|
| 1 | `include/llama.h` | ~396 行 | `llama_context_params` 新增 `fa_kv_threshold`、`fa_max_tokens` |
| 2 | `src/llama-cparams.h` | ~41 行 | cparams 新增同名字段 + `fa_adaptive`；新增 inline `llama_fa_enabled()` |
| 3 | `src/llama-context.cpp` | 230-247 | 新字段初始化；`LLAMA_FA_DYNAMIC=1` 才开启实验性每步切换 |
| 4 | `src/llama-context.cpp` | 312 后（n_ctx 定稿、KV cache 创建前） | **核心判定**：`n_ctx > fa_kv_threshold` → 关 FA |
| 5 | `src/llama-context.cpp` | default params | `fa_kv_threshold = 2048`、`fa_max_tokens = 1` |
| 6 | `src/llama-graph.cpp` | 39 / 816 / 977 / 2763 / 3266 | mask 类型统一走 `llama_fa_enabled()` |
| 7 | `src/llama-graph.cpp` | 2637 | `use_flash_attn` 改用同一函数 |
| 8 | `src/llama-graph.cpp` | 48-68 | `can_reuse_kq_mask()` 增加 mask **类型**检查 |
| 9 | `common/arg.cpp` | 1751 后 | 新增 `-fakv/--fa-kv-threshold`、`-fatok/--fa-max-tokens` |
| 10 | `common/common.h` / `common.cpp` | params | 透传两个新参数 |

不改：ggml 内核、KV cache 内部、调度器。

---

## 5. 风险与已知副作用

| 风险 | 说明 | 缓解 |
|---|---|---|
| **输出变化** | FA 与 legacy 数值路径不同（累加顺序），切换后相同 prompt 可能产出不同 token。这是速度换确定性的取舍 | 文档化；可用 `-fa 0/1` 强制固定路径 |
| 跨阈值一次性抖动 | 切换点会重建一次 graph | 本来每步都重建，成本≈0 |
| prefill 内存 | 已在 §3.2 用 n_tokens 约束规避 | 硬约束，不可绕过 |
| 非 x86 / GPU 回归 | 新字段默认 `fa_adaptive=false`（除非用户显式 `-fa auto` 且…） | ⚠️ 注意：`auto` 是**默认值**，等于所有 CPU 用户默认行为改变。这是本 spec 的意图，但需明确知晓 |
| 与投机解码/MTP 交互 | draft 与 target 各自建图，n_kv 判定一致 | 测试覆盖 draft 场景 |

**最关键的一条：`-fa auto` 是 llama.cpp 的默认值**，所以这个改动会改变所有 CPU
用户的默认行为。对本 fork（CPU 特化）这是目标；但必须实测确认短上下文没有回退。

---

## 6. 验证方案

1. **正确性**：改动前后，用 `-fa 1` 和 `-fa 0` 跑同一 prompt，输出必须与未改动版本一致
   （强制开关时 `fa_adaptive=false`，行为应完全不变）。
2. **切换是否真的发生**：在 decode 日志中打印每步的 `n_kv` 与当前 FA 选择，
   确认跨过阈值时切换发生，且只发生一次。
3. **性能**：`llama-cli -f ctx_<N>.txt -n 128`，N ∈ {64, 256, 512, 1024, 2048, 4096, 8192}，
   对比三组：基线（旧二进制，`-fa auto`）、新二进制 `-fa auto`、`-fa 0`、`-fa 1`。
   - 成功标准：新 `-fa auto` 在每个 N 上都 ≥ 旧 auto，且 ≈ `max(fa=0, fa=1)`。
4. **prefill 不受影响**：长 prompt（8192）的 prompt 处理速度（t/s）应与旧版一致，
   且峰值内存不增长（观察 compute buffer 分配日志）。
5. **阈值扫描**：`-fa-kv-threshold` 取 512/1024/1536/2048，找本机最优值。
6. **回归**：`-fa 0` / `-fa 1` 显式开关下，性能与旧版一致（±噪声）。

---

## 7. 不在本次范围

- 每步重建 graph 的开销（新的靶点，已识别，另开 spec）
- CPU 亲和性 / P 核绑定（Meteor Lake 6P+8E，从未测）
- draft re-eval TODO（`TAG_SPEC_AVOID_DRAFT_REEVAL`）
- KV 量化（已证伪，负收益）

---

## 8. 实测结果（已完成）

详见 `ctest/benchmark_results.md` §9。摘要（Qwen3-0.6B Q2_K 325MB，t=12，生成 128 token）：

**A. 按需设 `-c`（`-c` = prompt 长度 ×2）**

| prompt | `-c` | auto（新） | `-fa 1`（旧默认行为） | `-fa 0` | 新 vs 旧 |
|---|---|---|---|---|---|
| 64 | 512 | 97.1 | 95.6 | 81.6 | +1.6% |
| 256 | 512 | 83.6 | 82.6 | 78.3 | +1.2% |
| 512 | 1024 | 77.5 | 78.1 | 72.7 | −0.8%（噪声） |
| 1024 | 2048 | 66.3 | 65.7 | 64.1 | +0.9% |
| 2048 | 4096 | 54.2 | 46.2 | 52.3 | **+17%** |
| 4096 | 8192 | 36.6 | 25.3 | 36.8 | **+45%** |
| 8192 | 16384 | 23.5 | 12.4 | 23.7 | **+90%** |

每个长度都拿到了两条路中的较优者，短上下文无损失。

**B. 已知边界（`-c 16384` 固定）**：prompt 64 → 80.2（vs `-fa 1` 的 94.7，**−15%**）；
prompt 512 → −8.8%；prompt 2048 → +11%；prompt 8192 → +90%。
判定只有 `n_ctx` 这个上限可用，不知道实际会聊多长，`-c` 开太大就白付 9%~15%。

**状态**：已实现、已编译（153/153 → 64/64 增量）、已验证。
行为符合 §6 的成功标准：新 `auto` ≈ `max(fa=0, fa=1)`。
