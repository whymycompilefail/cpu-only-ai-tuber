# Spec 06：ASR 延迟初始化（Open-LLM-VTuber fork）

> 项目：Ai_edge_deployment
> 日期：2026-10-11
> 状态：**已实现 + 已起栈回归验证**
> 上游：Open-LLM-VTuber v1.2.1（MIT）
> 改动文件：`Open-LLM-VTuber/src/open_llm_vtuber/service_context.py`

---

## 0. 一句话

把 ASR 引擎的构造从「启动时无条件执行」改成「第一次真正读到它时才执行」，
让纯弹幕场次不再为一辈子用不到的语音模型付启动代价。

---

## 1. 动机

上游 `service_context.py` 在 `load_from_config()` 里无条件调用 `init_asr()`。
对这套栈的具体后果：

- **冷机器要下 230 MB。** `asr/sherpa_onnx_asr.py:174` 硬编码了自动下载 URL
  （`github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/...tar.bz2`）。
  哪怕这一场一次麦克风都不碰，启动也会去拉它。
- **下载拿不到就是硬失败。** `init_asr()` 没有 `try/except`，而同一个文件里的
  `init_live2d()` 有降级（"Try to proceed without Live2D..."）。
  断网 / GitHub 不可达时，ASR 构建抛异常 → 整个后端起不来 → **弹幕链路也跟着死**，
  而弹幕链路根本不需要 ASR。
- 已知延迟构成里 **TTS 占 70~95%，LLM 只占 ~5%**，ASR 不在主链路的延迟预算内，
  所以动机纯粹是「启动成本 + 单点故障」，不是性能。

## 2. 为什么不能靠改配置「关掉」

`config_manager/asr.py:313` 里 `asr_model` 是 pydantic 的 `Literal`，只有 7 个值：

```
faster_whisper / whisper_cpp / whisper / azure_asr / fun_asr /
groq_whisper_asr / sherpa_onnx_asr
```

**没有 `off` / `none` / `disabled`。** 写任何别的值都会在配置校验阶段
ValidationError，后端根本起不来；`asr_factory.py` 的 else 分支也是直接
`raise ValueError(f"Unknown ASR system: ...")`，没有兜底。

⇒ 「默认关掉」这条路在配置层是死的，只能改代码。
（而且现在也不该关——麦克风是主播跟 AI 对话的主入口。）

## 3. 实现

`asr_engine` 从普通属性改成 **property**，调用点一行都不用动：

```python
@property
def asr_engine(self):
    if self._asr_engine is None and not self._asr_init_failed:
        asr_config = getattr(self.character_config, "asr_config", None)
        if asr_config is not None:
            try:
                self._asr_engine = self._build_asr(asr_config)
            except Exception as e:
                self._asr_init_failed = True
                logger.critical(...)
    return self._asr_engine
```

配套三点：

1. `__init__` 里改为 `self._asr_engine = None` + `self._asr_init_failed = False`。
2. `__str__` 读 `self._asr_engine`，否则打印日志本身就会触发加载（这个坑很隐蔽）。
3. `_asr_init_failed` 让失败的构建**只尝试一次**——否则每次说话都重试一次
   230 MB 下载。

`init_asr()` 保留为**显式预热入口**，语义与原版不同：它的失败**不吞异常**，
因为调它的人就是要 ASR，宁愿看见错误。

## 4. 验证

**单元级**（`ctest/test_lazy_asr.py`，mock `ASRFactory`，5 条契约全绿）：

| 契约 | 结果 |
|---|---|
| 无配置时不加载 | 0 次构建 |
| 有配置时首次读取才加载 | 1 次 |
| 连续读 5 次走缓存 | 仍 1 次 |
| 构建失败降级为 None 且不崩 | 重复读 5 次仅尝试 1 次 |
| 显式 `init_asr()` 仍可用 | 正常产出引擎 |

**起栈回归**（`bash ctest/run_stack.sh --wait`）：

- 启动日志的初始化序列是 `Live2D → TTS → VAD → Agent`，
  **没有 `Initializing ASR`** —— 改动前这一行必然存在。
- `curl -X POST /asr -F file=@xxx.wav` 之后日志才出现
  `Initializing ASR: sherpa_onnx_asr`（本地有权重，1 秒完成），
  返回 `{"text":"。"}`，后端全程无异常。
- 打 `/asr` 前后计数：0 → 1，正好一次。

## 5. 副作用与边界

- **麦克风功能不受影响**：首次用到音频时才构建，行为等价，只是晚一点。
- **纯弹幕场次**：永不构建，启动更快、离线可起。
- **降级后**：麦克风输入不可用，但弹幕链路照常。用户需要在日志里看到
  `Proceeding without ASR` 才知道原因。
- `ctest/asr_verify.py`（TTS 反读验证）依赖 ASR，无权重时会不可用。

## 6. 与发布的关系

SenseVoice 权重（228 MB）**不入库**：一来它是第三方权重，越出「仅源代码」边界；
二来 GitHub 单文件硬限 100 MB，留着整个 push 会被拒；
三来代码本来就会自动下载，不需要人工分发。
`.gitignore` 的 `Open-LLM-VTuber/models/` 覆盖的正是这个下载产物。

⚠️ 若要改用 Git LFS 承载它，**必须在首次 commit 之前配好 `.gitattributes`**。
