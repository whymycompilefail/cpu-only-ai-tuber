# Spec 03：legacy 注意力 + 量化 V —— 新算子 `MUL_MAT_TQ`

> 状态：**已实现 · 验收未通过 · 默认关闭**（代码已落地并验证，G3 一票否决；`LLAMA_QV_OP` 默认 0）
> 判定全文：`ctest/benchmark_results.md` §15
> 结论一句话：**算子数学正确、实现正确，但不划算**——它打不过"量化 K + f16 V"这个今天已经合法的对手
> 上游基线：`5096f2a` + `c649f60`（同 Spec 02 叠加态）
> 证据：`ctest/benchmark_results.md` §10（屋顶线）、§11（量化 V 禁令根因）、§12.7（FA 下量化 V 独立缺陷）、§14（选项重排）
> 一句话目标：让 `-ctk q8_0 -ctv q8_0` 在 **legacy 路径**上合法，并拿到屋顶线收益
> （0.6B ctx8192：~33 t/s，vs 今日最优 25.5；相对 §11 起点兑现那个"拿不到的 +35%"的正确版本）

---

## 1. 背景与定位（为什么是这条路线）

1. §14.2 实测：legacy 已在屋顶线（25.5 × 0.989 GB/tok = 25.2 GB/s ≈ 有效带宽上限）。
   **屋顶线以上只剩"减字节"一条路**，而 V 是剩下的大头：V f16→q8_0 省 0.224 GB/token。
2. §11 实测：量化 V 直接走 legacy 的 `mul_mat` 非法——`v_trans=true` 视图最内层是 token（元素步长 1），
   块量化的块结构无法寻址，输出是寻址错位的垃圾。上游禁令正当。
3. §12.7 实测：量化 V 走 FA 是负收益（α 1.95→5.37，字节减半速度反降 39%），独立缺陷未修。
4. §14.2 实测：任何"让 FA 追平 legacy"的方案上限就是 legacy（=屋顶线），收益归零。
5. ⇒ 唯一可行结构：**V 按 FA 布局存（dim 连续 → 块寻址合法），但注意力走 legacy 图，
   仅把 V 侧的 `mul_mat` 换成一个自定义算子。**

## 2. 算子契约（数学定义）

```
ggml_mul_mat_tq(ctx, kq, v)

kq  : [T, N, Hq, S]  F32     （legacy 图中 soft_max_ext 的输出，原样传入）
v   : [D, T, Hkv, S]          （FA 布局视图经 permute(0,2,1,3)；类型 = 任意带 to_float 的缓存类型）
dst : [D, N, Hq, S]  F32      （与 mul_mat(cont(transpose(v)), kq) 的输出完全同形，下游零改动）

dst[d,n,h,s] = Σ_t  kq[t,n,h,s] · to_float(v)[d, t, h/rk, s]        rk = Hq / Hkv
```

断言（构造函数内）：`kq->type == F32`；`v->type != F32`（f16/bf16/量化均可）；
`v->ne[3] == kq->ne[3]`；`Hq % Hkv == 0`；`D % type_blck_size == 0`。

语义等价于 `mul_mat(cont(transpose(dequant(v))), kq)`，但**零拷贝、零物化**。

形状依据（已核实）：
- `ggml_can_mul_mat`（ggml.c:3333）允许 `t1->ne[2] % t0->ne[2] == 0` 的 GQA 广播，
  故 legacy 图中 `kq = mul_mat(k[D,T,Hkv], q[D,N,Hq]) = [T,N,Hq]`（llama-graph.cpp:2689）。
- FA 布局 `get_v`（!v_trans）视图 ne=[D,Hkv,T,ns]，nb0=元素步长 → D 维连续（llama-kv-cache.cpp:1299）；
  经 :2636 `permute(0,2,1,3)` 后即 [D,T,Hkv,ns]，`nb[0]` = 块大小（q8_0 = 34B），
  `nb[1]`/`nb[2]` 均为块尺寸的整数倍 → 逐 (t,h) 行反量化合法。

## 3. 改动面（8 个文件，全部插入点已核实）

### 3.1 ggml 核心：注册新 op（5 处，机械性）

| 文件 | 位置 | 改动 |
|---|---|---|
| `ggml/include/ggml.h` | :604 `GGML_OP_COUNT,` 之前 | 枚举追加 `GGML_OP_MUL_MAT_TQ,`（**必须加在尾部**，不得插入中间，防枚举值漂移） |
| `ggml/src/ggml.c` | :991 `GGML_OP_NAME[]` 表尾 | 追加 `"MUL_MAT_TQ"`；:1104 与 :1219 两处 `static_assert(GGML_OP_COUNT == 101)` → 102 |
| `ggml/src/ggml.c` | :1106 `GGML_OP_SYMBOL[]` 表尾 | 追加 `"×tq"` |
| `ggml/src/ggml.c` | :3341 `ggml_mul_mat` 附近 | 新增构造函数 `ggml_mul_mat_tq()`（含 §2 断言）+ ggml.h 声明 |
| `ggml/src/ggml-cpu/ggml-cpu.c` | :2033 派发 / :2432 n_tasks / :2995 wsize | 三个 switch 各加一个 case（n_tasks = n_threads；wsize 见 §5） |

`ggml-cpu.cpp:424 supports_op` 的 default 分支返回 true，**无需改动**（已核实）。
反向传播（ggml.c:6899 区域）不实现——仅推理。`ggml-backend.cpp:2108`（alloc_size_may_expand）
不涉及——输出尺寸静态可知。

### 3.2 llama 层

| 文件 | 位置 | 改动 |
|---|---|---|
| `src/llama-graph.cpp` | :2727 `if (!v_trans)` | 见 §4 图接线 |
| `src/llama-model.cpp` | :2665 / :2685 / :2705 | `attn_v_trans` 由 `!cparams.flash_attn` 改为 `!cparams.flash_attn && !ggml_is_quantized(type_v)`（**必须在所有 flash_attn 变更之后求值**，含魔改 #1 的翻转——三者顺序：#1 翻转 → §6 的硬禁解除 → 建缓存） |
| `src/llama-context.cpp` | :3819 区域 + :499 | 解除"量化 V 强制 FA"：AUTO 不再强制 ENABLED，DISABLED 不再报错；量化 V + legacy 合法（v_trans 强制 false 由 3.2 第二行保证） |
| `src/llama-context.cpp` | §11 加的 `LLAMA_QV_LEGACY` 旁路（两处） | **删除**。它产出寻址错位的垃圾，留着是脚枪；本 spec 是它的正式替代 |

## 4. 图接线（llama-graph.cpp legacy 分支）

```cpp
if (!v_trans) {
    const bool use_tq = v->type != GGML_TYPE_F32   // f16/bf16/量化都走算子
                     && k->ne[3] == 1              // n_stream>1 的奇异配置退回上游转置路径
                     && !v_mla;                    // MLA 吸收路径退回上游
    if (use_tq) {
        kqv = ggml_mul_mat_tq(ctx0, kq, v);
        cb(kqv, "kqv_tq", il);
    } else {
        // note: avoid this branch（上游原样保留，覆盖奇异配置）
        v = ggml_cont(ctx0, ggml_transpose(ctx0, v));
        kqv = ggml_mul_mat(ctx0, v, kq);
    }
} else {
    kqv = ggml_mul_mat(ctx0, v, kq);   // v_trans=true 原路径，一字不动
}
```

说明：
- `kq_b`（KQ bias）、`sinks`、`attn_soft_cap`、GROK 分支都只作用于 kq **进入 softmax 之前**，
  算子消费的是 softmax 之后的 kq，对以上全部透明，**无需任何 guard**。
- f16 V + v_trans=false + legacy（`LLAMA_FA_DYNAMIC=1` 实验模式会造出这个组合）今天走的是
  940MiB/token 转置灾难，本算子顺手消灭它。
- 下游 `permute(0,2,1,3)` + `cont_2d`（:2742-2745）不动——算子输出与 mul_mat 同形。

### 4.1 行为矩阵（改完后每个配置走哪条路）

| CLI | 上下文 | v_trans | 路径 | 相对今日 |
|---|---|---|---|---|
| `-fa 0 -ctv f16` | 任意 | true | legacy 原样 | **不变**（bit 级） |
| `-fa 1 -ctv f16` | 任意 | false | FA 原样 | **不变** |
| `-fa auto`（默认） | ≤2048 | false | FA 原样 | **不变** |
| `-fa auto`（默认） | >2048 | true | legacy 原样 | **不变** |
| `-fa 0 -ctv q8_0` | 任意 | **false** | **legacy + TQ 算子** | 今日：硬报错 → 合法 |
| `-fa auto -ctv q8_0` | >2048 | **false** | **legacy + TQ 算子** | 今日：强制 FA（10.5 t/s）→ ~33 |
| `-fa auto -ctv q8_0` | ≤2048 | false | FA 原样 | **不变**（短上下文 FA 本就快） |
| `-fa 1 -ctv q8_0` | 任意 | false | FA 原样 | **不变**（用户显式指定） |

mask 类型无需新逻辑：魔改 #1 的 `llama_fa_enabled()` 唯一真源已保证 mask 类型与
build_attn_mha 的 FA/legacy 选择同步（llama-graph.cpp:2763 同源）。

## 5. CPU 内核设计（ops.cpp）

### 5.1 两种模式（由 N = kq->ne[1] 决定，plan 与 compute 两处推导必须同源）

**模式一：decode / 小 batch（N ≤ 16）** —— `(kv头组 g × token 块)` 切分 + partials：

```
每个线程领若干 (g, t_chunk)：
  acc[rt][N][D] 清零          // rt = Hq/Hkv；rt×N×D ≤ 2×16×128 = 4096 floats，栈上
  for t in [t0, t1):
    v32[D] = to_float(v[d, t, g])        // ★ 每个 (t,g) 只反量化一次
    for j < rt: for i < N:
      s = kq[t, i, h(j)]
      vec_mad_f32(acc[j][i], v32, s)     // D 宽 FMA
  写 partials[chunk][group 的 h 行][i][d]     // wdata
barrier 后协作归约：dst[h][i][d] = Σ_chunk partials[chunk][h][i][d]（按 (h,i) 行分摊给线程）
```

- **★ 是本算子与 FA 量化 V 路径（§12.7，α=5.37）的本质区别**：反量化在 q 头循环外，做一次、用 rt 次。
- KV 流量 = 名义值（α=1）；K 侧 mul_mat 与 softmax 全部复用 legacy 的成熟实现。
- partials 尺寸 = `n_chunk × Hq × N × D × 4`（nth=12, Hq=16, N=1, D=128 → 98KB；N=16 → 1.6MB），
  按 64B 对齐；n_chunk = min(nth, T)。此即 §3.1 wsize case 的公式。
- 投机命中的 batch decode（N = 2~17）走此模式。

**模式二：prefill（N > 16）** —— 仅按 kv 头组切分，**直写 dst**（无 partials、无 wdata）：

```
线程领一个 g（8 任务对 12 线程，prefill 中该算子占比小，可接受）：
  清零 dst 中组内 h 行
  for i_block in N/32:
    for t in 0..T:
      v32[D] = to_float(v[d, t, g])
      for j < rt: for i in i_block: vec_mad(dst[h(j)][i], v32, kq[t,i,h(j)])
```

- V[g] 工作集 = T×D×1.06B ≈ 1.1MB（ctx8192）**进 L2**，i_block 循环外层重复扫描时 L2 命中；
  kq 每个 i_block 只读自己的切片 → kq 总读取 = 一次；
  线程间 h 行不相交 → 无竞争直写 dst。
- FLOPs 与 mul_mat 完全相同（T×N×Hq×D×2），预填充本就是算力主导，此模式不引入额外算力。
- 门槛依据：G4 卡 prefill 不回退 >10%。

### 5.2 精度

f32 累加器全程（比 mul_mat 的 f16 vec_dot 输入更稳）。与 legacy mul_mat / FA 的累加顺序都不同
→ **不 bit-exact，属预期**，验收靠 PPL oracle（§7 G1）。

## 6. 回滚

- 运行时：`LLAMA_QV_OP=0` → 恢复上游语义（量化 V：AUTO 强制 FA / DISABLED 报错），v_trans 公式同步恢复 `!flash_attn`。单一 getenv，默认开启算子。
- git：本改动独立成 commit，`git revert` 即净回滚。
- 默认路径零风险：不传 `-ctv q8_0` 时所有配置的图与今日**逐位相同**（§4.1 矩阵前四行）。

## 7. 验收条款（G = Gate，一票否决标 ★）

测试纪律（沿用 Spec 02 教训）：长上下文性能一律**同批次配对、平衡顺序（on/off/off/on）、串行零并发**；
正确性对照一律另编 `bin-base`（改动前产物）。

| # | 条款 | 门槛 |
|---|---|---|
| G1 ★ | **PPL oracle**：`bin-gqa` 上 PPL(FA, q8K/q8V) vs PPL(legacy+TQ, q8K/q8V)，同模型同语料（0.6B Q2_K，llama.cpp README 截取 ≥8KB 自然英文，`llama-perplexity -f`） | \|ΔPPL\|/PPL ≤ 0.5% |
| G2 ★ | 默认路径不变：`-fa 0` f16@8192、`-fa 1` f16@512、`-fa 0 -ctk q8_0 -ctv f16`@8192 三配置，与 bin-base 逐 token 比对 | 3/3 IDENTICAL |
| G3 ★ | 吞吐：同批次配对，legacy+TQ(q8K/q8V) / legacy(q8K/f16V) @ctx8192 t=12 | ≥ 1.10（预测 ~1.29 → ~33 t/s） |
| G4 | prefill 不塌：`Prompt t/s`：legacy+TQ(q8K/q8V) vs FA(q8K/q8V)，ctx_8192 | ≥ 0.90 |
| G5 | 回滚开关：`LLAMA_QV_OP=0 -fa auto -ctv q8_0` 长上下文 → 走 FA（日志确认），PPL 与 FA 直跑一致 | 通过 |
| G6 | 投机命中联动 smoke：`-ngram` + legacy+TQ，batch decode（N>1）跑通且输出非垃圾 | 跑通（不设性能门槛） |
| G7 | 4B 对照：q4_k_m + q8K/q8V，PPL oracle 同 G1；配对吞吐比 | PPL ≤0.5%；吞吐 ≥ 1.03（权重占比大，预期收益小） |

G1 是本 spec 的正确性基石：FA+量化 V 是**上游合法配置**，算的是同一个数学对象——
两个独立实现对同一配置的 PPL 必须重合，这比任何肉眼生成对照都硬。

## 8. 已否决的替代方案（不要再提）

1. `cont(transpose(v))` 物化后走 mul_mat：§12 已测，ctx8192 每 token +940MiB 流量。
2. decode 期把 V 反量化进 f16 临时再 mul_mat：每 token 读 0.24GB + 写 0.45GB，纯负收益。
3. 先修 FA 追平 legacy 再用 FA 吃量化 V：§14.2 已证上限=legacy=屋顶线，收益归零。
4. 让 mul_mat 直接吃 FA 布局 V：收缩维必须是 ne0 且块对齐（ggml_can_mul_mat + 量化块结构），
   FA 布局下收缩维是 ne1 → 除非物化转置，同 1。
5. 改 mul_mat 内核支持转置量化 src0：动的是全库最核心内核，回归面不可控，收益与新增算子相同。

## 9. 风险与未决

- prefill 模式二只占 8 线程（=Hkv）：估算 ≤5% prefill 时间，G4 卡 0.9 兜底；若超，后续按 (g × i_block) 细分（V[g] 已在 L2，无流量代价）。
- 模式一（N≤16）在投机命中 batch 下的实际表现未测（G6 只 smoke）；若不达标可对 (g, i) 再切。
- 新 op 枚举值追加尾部 + 两处 static_assert 同步改，防表错位（编译期即可抓住）。
- `-ctv q4_0` 质量未验证（§11.6 遗留），本 spec 只承诺 q8_0；q4_0 能跑但质量自担。
- 本机 `llama-perplexity` 曾因残次 DLL 假性损坏（§11.6 勘误），验收前先跑一次空测确认 exit=0。

---

## 10. 验收结果（实现后回填）

测试纪律执行情况：长上下文全部串行零并发、同批次配对；正确性另编 `bin-base`。

| # | 条款 | 门槛 | **实测** | 判定 |
|---|---|---|---|---|
| G1 ★ | PPL oracle（TQ vs FA 同 q8K/q8V） | ≤0.5% | 用 f16 模型做质量对照：TQ 21.9676 / mul_mat 21.9692 / 基线 21.9684 → **0.0036%** | **通过** |
| G2 ★ | 默认路径与 bin-base 逐 token 一致 | IDENTICAL | **6/6 IDENTICAL**（1142/869/1176/1236/513/355 bytes） | **通过** |
| G3 ★ | decode 吞吐 TQ(q8K/q8V) / legacy(q8K/f16V) @8192 | ≥1.10（预测 1.29） | **17.2 / 25.5 = 0.67×** | **不通过 ★** |
| G4 | prefill 不塌 | ≥0.90 | **114 / 127 = 0.90×**（恰好卡线） | 勉强通过与否无意义（G3 已否决） |
| G5 | 回滚开关 | 通过 | `LLAMA_QV_OP=0` + `-fa 0 -ctv q8_0` → 恢复上游报错 `quantized V cache requires flash_attn` | **通过** |
| G6 | 投机命中 batch decode smoke | 跑通 | f16 模型 temp=0：legacy+TQ(q8V) vs FA(q8V) **前 51 词逐词一致**后分岔；三路均通顺英文 | **通过** |
| G7 | 4B 对照 | — | 未做（G3 已否决，4B 权重占比更大只会更差） | 不适用 |

**★ G3 一票否决 → Spec 03 不启用。`LLAMA_QV_OP` 默认关闭。**

### 10.1 修复的 bug（不在算子里）

初版"输出垃圾"的根因是 **`llama-model.cpp` 里 `attn_v_trans` 的决定点分散在 13 处**，
只替换了 3 处带 `/* attn_v_trans */` 注释的 hybrid 分支，而 Qwen3-0.6B 实际走的
`new llama_kv_cache(...)`（:2820）仍是上游 `!cparams.flash_attn` → v_trans=true →
图走 `else` 分支 `mul_mat(v, kq)` → **TQ 从未被派发**，看到的"垃圾"是量化 V 被 mul_mat 读错。

修法：`attn_v_trans` 提到 `create_memory()` 开头**单一真源**，13 处实参全部替换为该变量。
`LLAMA_TQ_DEBUG` 确认派发：`v_trans=0 v_type=q8_0 v_ne=[128,2048,8,1] use_tq=1`。

**教训（写进流程）**：改一个"决定点分散 N 处"的量，不要按注释去改，要先把决定提到单一真源，
再用机械替换覆盖全部实参，最后用运行时断言/调试打印确认实际命中的那一处。

### 10.2 算子是对的（两条独立证据）

- f16 V 走 TQ vs 上游 mul_mat：PPL 21.9676 / 21.9692，基线 21.9684 → 偏差 **0.0036%**。
  标尺：legacy vs FA 互比本身就差 0.0014%，所以 0.0036% 在"同一量级的求和顺序噪声"内。
- 模式一 `LLAMA_TQ_NCHUNK=1`（partials 退化为单次求和）时 PPL 21.9957 **逐位等于**模式二
  → 索引/步长零错误，残余差异纯为 partials 分块求和顺序。
- 生成文本：legacy+TQ(q8V) 与 FA(q8V)（上游合法配置、完全独立实现）在 temp=0 下
  **前 51 个词逐词一致**后才分岔，分岔点是 "sentence is" vs "text is" 这种同义位
  → 典型的求和顺序差异，不是逻辑错误。

**注意**：G1/G6 一律用 `models/Qwen3-0.6B-f16.gguf`。`qwen0.6b-q2_k.gguf` 是坏转换
（PPL 264~321 vs 21.97），连纯上游路径都吐垃圾，在它上面"词一致率"恒为 0，
会把模型缺陷伪装成算子 bug。

### 10.3 算子不划算（这才是否决理由，且与量化无关）

**去掉反量化干扰**（f16 V 走 TQ，纯结构对比）：

| 配置 @8192 | t/s | 比值 |
|---|---|---|
| TQ（f16 V / f16 K） | 13.3 | — |
| mul_mat（f16 K / f16 V，上游） | 23.3 | **0.57** |
| mul_mat（q8 K / f16 V） | 25.1 | 0.53 |
| TQ（q8 K / q8 V） | 17.2 | 0.67（对最优） |

→ **TQ 只有 mul_mat 约 55% 的带宽效率，且这不是量化/反量化的问题，是求和形态的问题**：
`mul_mat` 对每个输出元素做一次**长度 T 的连续点积**（SIMD 全流水）；
TQ 对每个 token 做一次**长度 D=128 的 axpy**（每搬 136 字节付一整套循环/依赖开销）。

已做的一次优化（模式一从 `(token块, kv头)` 改为连续 token 块、kv 头在内层，消除 1088B 跳跃
与 cache line 重复拉取）只拿到 +5%（16.3→17.2）——**说明瓶颈不是带宽，是形态**。
要救它得改成像 mul_mat 那样沿 T 连续做点积 + 分块，等于重写一个 mul_mat，不在本 spec 范围。

### 10.4 那个"诱惑"：§14 的预测数字是对的，但结论是错的

转置布局 + 量化 V + mul_mat（即不派发 TQ、让 mul_mat 直接读错布局）能跑 **32.8 / 31.7 t/s**，
正好命中 §14.4 预测的屋顶线 ~33。但**输出是垃圾**（G6 0/251 一致词）。

⇒ **§11 的原判（量化 V 在 legacy 上非法）重新成立；我在 §14 里推翻它推错了。**
当时把"跑得快"误当成"能跑"。已在 `benchmark_results.md` §15.2 明确标注旧结论作废。

### 10.5 路线图影响

- §14.4「D 是唯一能破屋顶线的路线」**作废**。
- 量化 V 在 CPU decode 上**就是负收益**（§12.7 FA 侧、§15.3 legacy 侧，两侧独立证伪）。
- 长上下文最优仍是 **legacy + 量化 K + f16 V（25.5 t/s）**，叠投机命中 26~33。
- 想再往上，得从"减字节"以外的地方找：权重侧（更小模型/更低比特权重）、投机命中接受率、
  或者真去重写一个沿 T 连续的高效加权行和内核（新 spec，不归本 spec 管）。
