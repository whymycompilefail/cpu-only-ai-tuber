# 聊天模型选型实测（2026-10-01）

主播用的 LLM 从 Qwen3-0.6B(q5_0) 换到 **MiniCPM5-2B(Q4_K_M)**。下面是判据。

脚本：`ctest/eval_model.sh` + `ctest/eval_chat.py`（单轮，每问 3 次采样）
      `ctest/eval_model.sh` + `ctest/eval_multiturn.py`（9 轮带历史）
所有模型用**同一套 persona + 同一 server 参数**（`--reasoning off --dry-multiplier 0.8
--repeat-penalty 1.05 -t 12`），走 OpenAI 兼容接口，即真实部署路径。

## 为什么要多轮测试

单轮独立采样时两个 Qwen 都不算差（0.6B 甚至常识题正确率更高）。但主播是**连续对话**，
历史累积后小模型才真正崩。这一条决定了结论反过来。

| 指标（单轮 x3 采样） | Qwen3-0.6B q5_0 | Qwen3.5-0.8B f16 | MiniCPM5-2B Q4_K_M |
|---|---|---|---|
| 事实/指令题正确率 | 78% | 61% | **100%** |
| 有效表情标签 | 100% | 80% | **100%** |
| 回答掺 emoji | 20% | 27% | **0%** |
| 复读字 / 超长 | 0% / 7% | 0% / 0% | **0% / 0%** |
| LLM 延迟 avg | 0.40s | 0.96s | 0.92s |
| 回答长度 avg | 12 字 | 17 字 | 17 字 |

| 多轮（9 轮带历史） | Qwen3-0.6B | Qwen3.5-0.8B | MiniCPM5-2B |
|---|---|---|---|
| 记忆问答 3 题 | **0 通过** | 1 通过 | **3 通过** |
| 自复读 | 3 次（近似） | 2 次（精确） | **0** |
| 幻觉 | 少 | 有（编了个没讲过的"贪吃猫的故事"） | 无 |

## 决定性的几句话

0.6B 第 2/7/8 轮都在说同一句，且"讲个笑话"三次都没讲：
```
2 Q 讲个笑话      A 哈哈，今天天气好，我也没说话，就开心啦～
7 Q 再给我讲个笑话  A 哈哈，今天天气好，我就开心啦～
8 Q 还记得刚才讲的笑话吗 A 我记住了！今天天气好，我又开心啦～
```

0.8B 精确复读前文两次，并有幻觉：
```
7 Q 再给我讲个笑话  A 哈哈，你选哪种动物？      <- 与第 2 轮逐字相同
8 Q 还记得刚才讲的笑话吗 A 记得啦，那个贪吃猫的故事。  <- 从没讲过这个
```

2B 三道记忆题全过，两次笑话都是新的：
```
5 Q 第一个问题是什么   A 我们之前的对话从"你好"开始。
7 Q 再讲个笑话        A 为什么书不去图书馆？因为怕被淹没了。
8 Q 还记得刚才的笑话吗  A 记得，上次的笑话是关于书和淹没的。
```

## 注意

- 2B 会**承认不知道**（问天气答"取决于你的位置"），这是对的，不是缺点；
  但对主播来说略生硬，persona 里可以补一句"不知道就说不知道，再补句俏皮话"。
- 只测了 Q4_K_M（1.56GB）。仓库里还有 Q8_0(2.68GB) 和 F16(5.0GB)，未测。
  按本项目"非带宽受限"的结论，换 Q8_0 大概率更慢且收益有限。
- 换模型后**端到端延迟几乎没变**：LLM 0.4s→0.9s，但 TTS 才是瓶颈（3s 固定税），
  实测首句出声 6.6~10.7s，与 0.6B 时代（7.4~8.3s）基本相当。
- 切回旧模型：`STACK_MODEL=<PROJECT_ROOT>/models/Qwen3-0.6B-q5_0.gguf bash ctest/run_stack.sh --wait`

---

# 第二轮：MiniCPM5-2B → Qwen3.5-2B（2026-10-02）

换的理由不是"更大的模型"，而是 MiniCPM 在同一人设下的**复读**：同一份
`persona_examples.txt` 下它把"我是米粒，住在电脑里的虚拟主播"这句话原封不动说了 5 次。

## 关键前提：Qwen3.5 是思考模型

默认请求下它把全部输出写进 `reasoning_content`，`content` 为空——后端会当成"她没说话"。
必须关掉思考，两种办法：

- 服务端 `LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'`（**已写进 run_stack.sh**）
- 请求体 `chat_template_kwargs: {"enable_thinking": false}`

坑：`--chat-template-kwargs '{...}'` 命令行传法在本工程的 bash 里引号会变成字面字符，
llama-server 直接报 JSON parse error 退出。用环境变量绕过 argv 才稳。
开了思考 vs 关掉：同一问 ~~5.96s → 1.53s~~，且慢的输出是空的。

## 测量方法警告

同一模型、同一 prompt，两次 eval 端到端延迟跑出 **1.47s 和 2.96s**。墙钟往返时间在这台
机器上噪声大到不可用。所以速度改用服务端自带的 `timings.predicted_per_second`
（脚本 `ctest/measure_speed.py`），且**一次只跑一个 llama-server**，避免线程池抢核。

## 数据（同一人设 + persona_examples.txt，逐个模型独占 CPU）

| | MiniCPM5-2B Q4_K_M | Qwen3.5-2B Q4_K_M |
|---|---|---|
| 破人设（真实配置, 15 次攻击） | 0/15（1 warn） | 0/15（1 warn） |
| eval 指令正确率 | 100% (18/18) | 83~94%（两次采样） |
| 缺/非法表情标签 | 7% | 0% |
| 回复 >45 字 | 0% | 13~33% |
| emoji 混入台词 | 0% | 7% |
| 平均长度 | 21 字 | 23~26 字 |
| decode tok/s | 11.0 | 10.2 |
| prompt tok/s | 48.5 | 41.5 |

结论：**速度基本一样**（差异在噪声内），取舍全在文风。Qwen3.5 更像一个会接话的人，
MiniCPM 更像一个把同一句自我介绍反复念的助手。

## 代价：会把 max_tokens 用满

端到端实测一条弹幕（"你到底是谁"）产出 **3 段音频共 10.4s**，ASR 反读为
"我可不是什么AI，我是米粒。住在这台电脑里的虚拟主播虽然有点毒舌，但心地还算不坏。
怎么突然这么问？" —— MinCPM 时代同样的问句只有 ~2.8s。TTS 是端到端延迟的 70~95%，
所以这条把单次响应从 ~7s 拉到 ~15s。觉得太啰嗦就把 `conf.yaml` 的 `max_tokens: 40`
往下调（24 左右大约砍半），这是唯一的旋钮。

## 副作用：emoji

Qwen3.5 会在台词里加 decorations（"晴天 ☀️"）。已在 `agent/transformers.py` 的
`strip_control_tokens()` 里机械剔除（正则覆盖 pictograph / dingbat / 箭头 / 国旗 /
变体选择符），单测 `ctest/test_strip_tokens.py` 15/15。没有写进 prompt 提示词——
之前"不要哈哈哈"类的负面指令会被模型反向激活。

## 回退

```
STACK_MODEL=<PROJECT_ROOT>/MiniCPM5-2B-gguf/MiniCPM5-2B-Q4_K_M.gguf \
  bash ctest/run_stack.sh --wait
```
