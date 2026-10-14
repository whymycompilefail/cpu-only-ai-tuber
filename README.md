# cpu-only-ai-tuber

**一台没有显卡的笔记本，真的把 AI 主播挂上了 B 站直播。**

> A local AI VTuber stack that runs end-to-end on CPU only — bilibili chat / your
> microphone → Qwen3.5-2B → Qwen3-TTS → Live2D — plus a CPU-tuned llama.cpp fork
> and the measurements behind every decision, including the ones we rejected.

参考机器：**Intel Core Ultra 7 155H，22 线程，无 GPU。**

| 环节 | 用的东西 |
|---|---|
| 聊天 LLM | `Qwen3.5-2B` Q4_K_M（2026-10-02 起，取代 MiniCPM5-2B） |
| 语音合成 | `Qwen3-TTS-12Hz-0.6B-Base` 朗读 + `1.7B-VoiceDesign` 造参考音色 |
| 推理引擎 | 本仓库的 llama.cpp fork（`llama-server`，OpenAI 兼容） |
| 前端表演 | Open-LLM-VTuber + Live2D（Cubism 模型自备，见 `ASSETS.md`） |
| 输入 | B 站直播间弹幕，或你自己的麦克风 |

它不是桌宠，不是对话 demo，**是真的对着直播间跑的**——这个前提会改变几乎所有优化决策（见下）。

---

## 链路

```
  B站直播间标签页                      Live2D 页面 (localhost:12393)
        │ MutationObserver                    │ WebSocket 被劫持复用
        ▼                                     ▼
  danmaku_pump.py  ──HTTP──▶  danmaku_bridge.py (:8765)
   (CDP 取出)

        │  ws://127.0.0.1:12393/client-ws
        ▼
  VTuber 后端 (:12393)  ──▶  llama-server (:8099)  ──▶  Qwen3.5-2B
        │                                                  │ 文本
        ▼                                                  ▼
   Live2D 表演  ◀────────────────────────────  Qwen3-TTS 合成语音
```

完整接线与每一步的验证命令在 **`LIVE_RUNBOOK.md`**。那份文档存在的原因是：这条链路有若干
失败模式是**静默的**——进程活着、日志干净、零报错，但她就是不开口。

---

## 三条最值钱的结论

这三条都是实测出来的，都不符合"AI 主播优化"的直觉，都能在本仓库里复现。

### 1. 别急着压 tok/s —— LLM 不是端到端的大头

压 tok/s 看起来最像在优化延迟，实际收益极小：

- **一轮健康回合 15～32 秒，绝大部分是 TTS 合成**（`LIVE_RUNBOOK.md`）
- LLM 侧 TTFT 优化到 391 ms 之后，占一轮耗时的 **2.7%**（`ctest/benchmark_results.md` §16.3）
- 桥接层的实测：引擎侧一轮 ~7-8 秒 ⇒ **上限约 8 条回复/分钟**，而中型直播间产出
  **10～50 条/分钟**（`ctest/danmaku_bridge.py` 文件头）

（后两条不是矛盾的：前者是含排队与表演的完整回合，后者是引擎侧单轮成本的上限推算。）

推论很直接：**不回应大多数弹幕是设计，不是缺陷**——桥接层在忙时**硬丢弃**而非排队，
否则 AI 永远落后五分钟，回答的是早已没人记得的问题（`ctest/danmaku_bridge.py` §Why this exists）。
预算也因此该从"更快"换成"更像"（更大或更会演的模型），而不是省那两秒。

### 2. 这台机器不是带宽受限 —— "减字节 = 提速"的推导在这里作废

实得带宽随每元素字节数**下降**而非上升（`B/elem` 从 Q8_0 的 35.3 降到 Q5_0 的 28.3 GB/s）。
所以真正的瓶颈是**每元素指令成本**，压量化位宽换不来线性提速。
详见 `specs/quant-dot-efficiency.md`。

### 3. 破人设的病灶是 RLHF 的诚实性先验，不是模型太小

被问身份就答"因为我是 AI 助手"——换更大的 Instruct 模型大概率**更糟**（越对齐越爱自陈）。
而且去掉 persona 里的 "AI" 字样，破人设率 **一字未变**（`ctest/probe_identity.py`）。

**有效解是把示范写进对话历史，而不是写进 system prompt：3/15 → 0/15。**
落地文件：`Open-LLM-VTuber/prompts/persona_examples.txt`。

> 写示范时别给观众真会问的问题写答案——模型会整句照抄，那比破人设更像机器人。

### 顺带：Qwen3.5 是思考模型

不关掉 thinking，回复会全部落进 `reasoning_content` 而 `content` 是空的
⇒ 表现为"她什么都不说"，且**不报任何错**。本项目用环境变量：

```bash
export LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'
```

⚠️ 不要改写成命令行 `--chat-template-kwargs '{...}'`——shell 会把花括号字面塞进去，
llama-server 启动即崩。

---

## 仓库里有什么

| 目录 | 说明 |
|---|---|
| `llama.cpp/` | 我们的 CPU 特化 fork。相对上游 `5096f2a` 改了 **15 个文件 / +1121 −173 行**，详见 `patches/README.md` |
| `patches/` | 上述魔改的完整 diff，可重放到干净的上游 checkout |
| `Open-LLM-VTuber/` | 上游（MIT）**+ 我们的一处魔改**：ASR 延迟初始化，见 `specs/open-llm-vtuber-lazy-asr.md` |
| `ctest/` | 自研工具：起停栈、弹幕桥接、破人设探针、声线批量生成、发布前隐私扫描 |
| `specs/` | 每次改动**为什么这么做**，附实测数据。含被否决的方案 |
| `ASSETS.md` | 模型权重 / 音色 / Live2D 形象去哪拿，以及各自的协议 |

关于 `llama.cpp/` 有一点必须知道：它的 `.git` 被改名成了 `.git.fork-backup/`。
**这不是删历史**——只要目录里存在 `.git`，外层 `git add` 就只会记一个 gitlink，clone 的人
拿到空目录。改回来一条命令：`mv llama.cpp/.git.fork-backup llama.cpp/.git`。

---

## 快速开始

> ⚠️ 诚实提示：这套东西是在**一台** Windows 机器上跑通的。脚本里有明确的 Windows 假设
> （`taskkill` / `netstat` / `.exe` / 路径写法），并且是用 Git Bash 跑的。
> 换机器大概率要改，尤其是进程管理和路径那几处。它不是"clone 下来就能跑"的项目，
> 更像一份带完整证据链的运行手册。

1. **编译 fork**（需要 CMake + MSVC/GCC）

   ```bash
   cd llama.cpp && cmake -B build && cmake --build build --config Release
   ```

2. **创建 Python 环境**

   ```bash
   cd Open-LLM-VTuber && python -m venv .venv
   .venv/Scripts/python.exe -m pip install -r requirements.txt
   ```

   依赖如果装不顺，以 `Open-LLM-VTuber/README.md`（上游）为准——那份才是它的第一手文档。

3. **取权重** —— 仓库里一个字节权重都没有，按 **`ASSETS.md`** 逐个下载
   （`Qwen3.5-2B` / 两个 `Qwen3-TTS` / Live2D 自备模型）

4. **写 `Open-LLM-VTuber/conf.yaml`** —— 该文件不入库（含本机绝对路径）。
   起点：`Open-LLM-VTuber/config_templates/conf.default.yaml` +
   `Open-LLM-VTuber/config_templates/qwen3_tts_local.snippet.yaml`

5. **起栈**

   ```bash
   bash ctest/run_stack.sh --wait
   ```

   然后打开 `http://localhost:12393`（用 Chrome/Edge，内置预览不支持麦克风）。

6. **要接真实弹幕**：先把 `cp ctest/live.local.example.sh ctest/live.local.sh` 填好房间号，
   再照 **`LIVE_RUNBOOK.md`** 走。浏览器侧需要交互（首次要扫码登录），所以没塞进脚本。

   麦克风也不用等 ASR 权重下载：后端已改成**延迟初始化**，不说话就不加载；
   ASR 挂了也不会拖垮弹幕链路。

常用：`ctest/measure_speed.py`（干净测速）、`ctest/probe_identity.py`（破人设探针）、
`ctest/asr_verify.py`（TTS 音频反读验证）。

---

## 仓库里没有什么

**任何模型权重、参考音色 `.wav`、Live2D 形象、会话日志、venv。**

理由不只是体积：

- **权重和音色带了各自的协议**（Qwen 系列是 Apache-2.0），混进包里等于把最宽松的协议
  套到最受限制的东西上
- **几秒参考音频 = 一段能克隆出该嗓子的声纹**，默认不发
- **Live2D 形象按"不可分发"处理**——VTube Studio 导出的模型常见条款明确禁止二次分发
- **会话日志逐条记录 `<观众用户名> <弹幕内容>`**，那是别人的隐私

发布前请跑隐私扫描（注意：commit 之后 `--git-staged` 会因 index 无差异而**静默跳过**，
正确做法见 `ctest/scrub_scan.py` 的说明）。

---

## 负面结果也算成果

我们把自己证伪的方案也写进了 `specs/`，因为它们能帮别人省时间：

| 结论 | 出处 |
|---|---|
| draft 投机解码是**负收益**：干净测得 8.10 vs 基线 11.69 t/s（**慢 31%**），跨模型接受率 0.416。对照组：同模型自投机接受率 0.907 ⇒ 机制本身没问题，是 target/draft 不配 | `ctest/benchmark_results.md` §draft model |
| `MUL_MAT_TQ` 算子**数学正确、实现正确，但不划算** —— 打不过"量化 K + f16 V"，默认关闭 | `specs/legacy-quant-v-op.md` |
| Spec 02 的 KV 重排只部分通过验收（R2/R3/R8 未达标） | `specs/fa-gqa-loop-reorder.md` |
| Prompt Ledger 值得做，但**代码还没动** | `specs/prompt-ledger.md` |
| 0.6B 模型单轮看着还行，**历史累积后崩**（这才推翻了单轮测试的结论） | `ctest/benchmark_model_choice.md` |

---

## 已知缺口

- 脚本的 Windows 假设（见上）——只在一台机器、一种 shell（Git Bash）下验证过
- 部分历史 benchmark 输出快照已从仓库剔除（它们印着本机绝对路径），保留在本地工作区，
  文中引用的数字以 `ctest/benchmark_results.md` 的文字结论为准
- 隐私扫描的 pre-commit hook **不会随 git 推送**（git 不传播 hook），贡献者需自行执行
  `ctest/install_hooks.sh`；单人使用时注意 `scrub_scan.py --git-staged` 在 commit 之后
  会静默跳过（index 无差异）这个陷阱

---

## 许可

- 本仓库自己写的部分（`ctest/` `specs/` `patches/` 及根目录文件）：**MIT**，见 `LICENSE`
- `llama.cpp/`：MIT（上游 + 我们的修改）
- `Open-LLM-VTuber/`：MIT（上游 + 我们的 ASR 延迟初始化）
- 模型权重：**Apache-2.0**，见 `ASSETS.md`

本仓库不分发任何权重或美术资产，因此对应的再分发义务不触发。
