# Spec 04：Prompt Ledger —— 把 KV 复用纪律从"人守"变成"API 约束"

> 状态：**待实现**（基石已实测验证，代码未动）
> 判定全文：`ctest/benchmark_results.md` §21
> 结论一句话：**值得做** —— "易变内容放末尾"实测值 4.34×，而引擎的 `--cache-reuse`
> 证明救不了这条（单指针贪心，`head_p` 卡死），所以只能由调用方保证 ⇒ 需要这层机制
> 上游基线：`5096f2a` + `c649f60`（同 Spec 02/03 叠加态），**引擎侧零改动**
> 证据：`benchmark_results.md` §16（常驻 168×）、§18（持久化 19×）、§20（LCP 硬约束）、§21（基石 + cache-reuse 证伪）

---

## 1. 背景：为什么必须由调用方来做

1. §20 实测：KV 复用要求**逐 token 前缀相同**。改前缀第 4 个 token → 复用率 0.7%，
   439 token 里只剩 3 个能用，prefill 81 ms → 2218 ms（**27×**）。
2. §21.2 实测：上下文切成 `FROZEN / HISTORY / VOLATILE` 三区、VOLATILE 永远在末尾时，
   稳态每轮只付 **127 token**；把 VOLATILE 插到中间就要付 **551 token**（**4.34×**）。
   改 FROZEN 一个词 → `cache_n=3`，全毁。
   ⇒ **"易变内容放末尾"值 4.34×，值得被做成机制。**
3. §21.3 实测（本 spec 的决定性依据）：引擎**已内置**块级 KV 平移复用
   （`server-context.cpp:3238` 的 `seq_rm` + `seq_add(kv_shift)`，`--cache-reuse N` 开启），
   但**对本场景无效** —— `--cache-reuse 256` 下惩罚仍是 4.34×，与 0 完全一致。
   根因是 `3252-3276` 的单指针贪心：匹配失败时只 `head_c += 1`，**`head_p` 永不前进**。
   "在 FROZEN 之后插入新块"会让 `head_p` 一开始就指向 slot 里根本不存在的内容 →
   第一次匹配失败 → 后面 421 token 的 HISTORY 明明完整存在也复用不上。
   ⇒ **`--cache-reuse` 只救"块顺序不变、整体平移"（FIM 场景），救不了"前部插入"。**
   ⇒ **而"前部插入"正是 agent 工作流最常见的动作**（插入工具输出、插入检索结果、
      插入压缩后的历史）。引擎兜不住，只能调用方守。
4. §21.2 补充：违规的惩罚是**一次性的**（下一轮立刻回到 127），不会持续污染。
   ⇒ 机制的目标是让违规**不发生**，而不是发生后补救。

### 1.1 不做什么

- **不改 llama.cpp**。本 spec 全部落在一层新的编排层里。引擎已经给了
  增量 decode（默认开）、块级平移（覆盖不到）、跨进程 save/restore（§18.3）——够用了。
- **不做投机预生成**。§17 已判决不做（天花板 1.18~1.30×）。
- **不改模型、不改内核**。这是 serving 层的事。

---

## 2. 形态

一层 **编排层**（Python，进程名 `ctxd`），坐在 `llama-server` 前面，对外暴露
**OpenAI 兼容的 `/v1/chat/completions`**。调用方不再自己拼 prompt，只能走 Ledger 的 API。

```
调用方 ──► ctxd (:8091, OpenAI 兼容) ──► llama-server (:8080)
              │
              ├── ZoneLedger    只追加的分区账本（§3）
              ├── ViolationGuard  复用率哨兵（§6）
              └── Recall        外部记忆注入（§7，P2）
```

目录：`<PROJECT_ROOT>/ctxd/`

---

## 3. ZoneLedger：只追加的分区账本

### 3.1 数据结构

```python
class Segment:
    id:      int          # 单调递增
    zone:    Zone         # FROZEN | HISTORY | VOLATILE
    text:    str
    ntok:    int          # 由 server /tokenize 得到，构造时算一次并缓存
    born:    int          # 写入时的 turn 号
    sealed:  bool         # True = 不可再改（FROZEN 恒为 True）
```

`render()` 的排序规则：**按 zone 分组（FROZEN → HISTORY → VOLATILE），段内按 id 升序**。
这个顺序就是发给 server 的 token 顺序，也是 KV 前缀顺序。

### 3.2 API（刻意缺失的部分是设计，不是遗漏）

| API | 语义 |
|---|---|
| `seal(text) -> id` | 写入 FROZEN，立即置 `sealed=True` |
| `append(text) -> id` | 追加到 HISTORY |
| `set_volatile(text)` | **清空 VOLATILE 区**再写入。VOLATILE 恒在末尾 |
| `correct(id, new)` | 不修改历史；追加一条 `[correction of #id] new` 到 HISTORY |
| `render() -> str` | 按 §3.1 排序拼接 |

**不存在** `edit` / `insert` / `replace` / `remove` / `reorder`。
调用方拿不到任何能改变已写 token 的手段 —— 这就是本 spec 的全部要点。

### 3.3 四条规则的落点

| §20.5 规则 | 机制 |
|---|---|
| 1 系统提示锁死 | `seal()` 后 `sealed=True`；任何改动抛 `ImmutableSegmentError` |
| 2 不编辑历史 | 无 edit API；`correct()` 只能追加 |
| 3 压缩用追加不用替换 | `compact()` 见 §5 —— 靠 checkpoint + 追加实现，**不是替换** |
| 4 易变内容放末尾 | `set_volatile()` 是唯一入口，渲染时强制排最后 |

---

## 4. 验收门槛（可判定）

| # | 条款 | 门槛 |
|---|---|---|
| **G1** | 10 轮 only-append 对话，每轮 `cache_n/(cache_n+prompt_n)` | **≥ 90%**，且不随轮数下降 |
| **G2** | 稳态 `prompt_n` 与 `\|VOLATILE\|` 的偏差 | **±10%** |
| **G3** | 人为把 VOLATILE 插到中间，ViolationGuard 必须报出来 | **必须报 `VIOLATION`**，且报出改变的 zone |
| **G4** | 对 sealed 段调用修改接口 | **必须抛 `ImmutableSegmentError`** |
| **G5** | `rewind(cp)` 的 prefill 成本 vs 冷启动同长度 | **便宜 ≥ 3×** |
| **G6** | 端到端：10 轮总 prefill 时间 vs 直接打 llama-server（调用方自由拼 prompt，含一次现实的重排） | **下降 ≥ 3×** |

G1/G2 是本 spec 的核心价值，不过就是白做。

---

## 5. Checkpoint 与 rewind（规则 3 的必要配套）

### 5.1 为什么必须有

规则 3 说"压缩历史用追加，不用替换"。但**只追加会让上下文越来越长**，摘要加进去反而更长。
真正的压缩必须删掉旧段 —— 而删除改变前缀 ⇒ 全毁（§20.3）。

**唯一的出路是 rewind**：不"替换"历史，而是**回到某个早先的检查点，再追加**。
前缀从检查点起仍然有效，代价 = restore + 检查点之后的 prefill。

### 5.2 机制

- 每 N 轮（默认 5）或一个 zone 边界，在**空闲时段**调 `POST /slots/0?action=save`
- 实测成本（§18.3）：**save 465 ms，565.3 MiB**（q8_0 K + f16 V，85.4 KB/token）
- `rewind(cp_id)`：`action=restore`（**310 ms**）+ 按 Ledger 重放 cp 之后的段
- **淘汰**：只保留最近 K=3 个 + FROZEN 边界那一个；磁盘可重建，不做长期保留

### 5.3 成本模型（必须写清楚，别当成免费）

| 动作 | 成本 |
|---|---|
| save 一次 | 465 ms + 565 MB 磁盘 |
| rewind 一次 | 310 ms + (L − L_cp) 的 prefill |
| 保留 K=3 检查点 | ~1.7 GB 磁盘 |

对比：不 rewind 而直接改前缀 = **全额重算**（§20.3 实测 2218 ms @439 token，
在 30 k 上下文下会到 ~280 s）。所以 rewind 是划算的，但**不是零成本**，
save 必须放在空闲时段做。

---

## 6. ViolationGuard：零成本哨兵

server 每次响应都带 `timings.cache_n` 和 `timings.prompt_n`（§16.1 已确认这两个字段
就是"实际重算多少 token"）。Guard 只做一件事：

```
reuse = cache_n / (cache_n + prompt_n)
if reuse < 0.9 and turn > 1:  log WARNING + 诊断（哪个 zone 相对上一轮变了）
```

诊断方法：Ledger 有每段的 `ntok`，比较本轮与上轮的段列表即可定位。

**零额外开销**——数据本来就在响应里，不需要额外请求。

---

## 7. Recall：把知识移出上下文（根治方向，P2 单独交付）

### 7.1 为什么是根治

§20.7 的结论：进了上下文的东西才要付 prefill；放在外部的东西**一遍都不用读**。
`ops.cpp` 一个文件 138,774 token（§19.2）——把它整份塞进上下文既不可能也不该。

### 7.2 机制

- **外部记忆库**：项目文件的**索引**（路径 + 顶层符号/函数签名 + 一段摘要），**不是全文**
- `recall(query) -> [snippet]`：关键词 / 符号检索（本机无 sklearn，按 §17 的做法自己写）
- **注入点强制走 `set_volatile()`** —— 即检索结果永远在 VOLATILE 区末尾

### 7.3 硬约束（最容易犯错的地方）

**检索结果绝不能插进 HISTORY 中间。** 每轮检索结果都不同，插中间等价于每轮改前缀
⇒ 4.34× 惩罚 + 后续全毁。这条要写成断言，不是注释。

---

## 8. 交付分层

| 优先级 | 内容 | 依赖 |
|---|---|---|
| **P0** | `ZoneLedger` + append-only API + `ViolationGuard` | 无（G1~G4） |
| **P1** | `Checkpoint` + `rewind` | P0（G5） |
| **P2** | `Recall` 外部记忆 + 注入 | P0（G6） |

P0 是全部价值的所在，且不需要动引擎。

---

## 9. 已知边界与风险

1. **VOLATILE 变大时代价线性上涨**。若工具输出 5000 token，稳态每轮就要付 5000。
   缓解：VOLATILE 内部再分"稳定前缀 / 易变尾部"，或对超长输出先截断再注入。
   本 spec 不解决，但 Guard 会把 reuse 掉下来这件事报出来。
2. **rewind 的语义改变对话**。回退后模型"忘记"了被丢弃的段，这与"压缩历史"的
   意图一致，但调用方必须知道这不是无损操作。
3. **85.4 KB/token 是 Qwen3-0.6B / 28 层 / 8 kv head 的数字**，换模型要重算（§18.7）。
4. **OpenAI 兼容层要处理 streaming**。§18.5 实测流式首 chunk 86 ms，是本方案体验的
   重要来源，不能因为加了编排层就退化成非流式。
5. **本 spec 不验证"agent 自主循环"**。§19.8 遗留：本项目交互形态是"人直接指挥"，
   G6 的对照场景只能靠人工构造一次现实的重排来近似。

---

## 10. 判定回填（实现后填）

| # | 门槛 | 实测 | 结论 |
|---|---|---|---|
| G1 | ≥90% 且不下降 | | |
| G2 | ±10% | | |
| G3 | 必须报 VIOLATION | | |
| G4 | 必须抛异常 | | |
| G5 | ≥3× | | |
| G6 | ≥3× | | |
