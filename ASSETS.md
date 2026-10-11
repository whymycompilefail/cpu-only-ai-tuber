# 大体积资产获取指南

本仓库**不包含任何模型权重、音色、Live2D 模型**，只保留让它们能被取到的方式。

这么做有两个原因，一个务实一个合规：

- 仓库要能 clone 下来就能读。塞进几 GB 权重，绝大多数人连 clone 都不会开始。
- **协议是分层的**：推理代码、训练权重、声音素材、美术素材各自有各自的授权，
  混在一个包里等于把最宽松的那个协议套到了最受限制的东西上。

## 各组件协议（以本地实际下载到的 LICENSE 为准，不是看网页标签）

| 组件 | 协议 | 依据 |
|---|---|---|
| llama.cpp | **MIT** | 仓库 LICENSE，Copyright The ggml authors |
| Open-LLM-VTuber | **MIT** | 仓库 LICENSE，Copyright (c) 2025 Yi-Ting Chiu |
| Qwen3.5 权重 | **Apache-2.0** | 模型目录内的 LICENSE 全文 + README front matter |
| Qwen3 权重 | **Apache-2.0** | 同上 |
| Qwen3-TTS 权重（0.6B / 1.7B） | **Apache-2.0** | README front matter `license: apache-2.0` |
| 自转换的 GGUF | Apache-2.0（继承原权重） | 是权重的衍生格式，`*.gguf` 不是新作品 |
| Live2D 角色 | **以原作者条款为准，通常禁止二次分发** | VTube Studio 导出的模型随附各自的授权条款 |

两个容易踩的点：

1. **代码协议 ≠ 权重协议。** Qwen3-TTS 的 GitHub 仓库是代码，HF / ModelScope 上
   是权重，两者不必一致。判断你在用的那份是什么，看**下载到的目录里的 LICENSE**，
   而不是平台页面上的徽章。
2. **既然本仓库不分发权重，Apache-2.0 的再分发义务就不触发。** 想改主意往仓库里
   放权重（尤其是自己转的 GGUF）时才会触发：需要随附 LICENSE、标注修改、处理
   NOTICE。那一天再来重读这条。

**唯一真正需要担心的是 Live2D 模型**，它不属于"宽松协议"这一边。见最后一节。

---

## LLM（聊天模型）

当前默认：`Qwen3.5-2B` Q4_K_M。

| 用途 | 获取方式 | 放到 |
|---|---|---|
| 转 GGUF 用的原权重 | `Qwen/Qwen3.5-2B`（HF / ModelScope 同名组织下的同名仓库） | `<root>/Qwen3.5-2B/` |
| 量化成品 | 用 `llama.cpp` 的 `convert_hf_to_gguf.py` + `llama-quantize` 自行转换 | `<root>/Qwen3.5-2B-GGUF/` |

选型的实测记录见 `specs/` 与 `ctest/benchmark_model_choice.md`：
换模型不是换一行配置，里面有破人设率、延迟、情绪标记可靠性的对比数据。

> **Qwen3.5 是思考模型。** 不关掉 thinking 的话，回复会全部落进 `reasoning_content`
> 而 `content` 是空的——表现为"她什么都不说"。本项目用环境变量传递：
> `LLAMA_ARG_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}'`
> 不要改写成命令行 `--chat-template-kwargs '{...}'`，shell 会把花括号字面塞进去，
> llama-server 启动即崩（踩过一次，再踩一次的话先看这里）。

## TTS（两个都要）

音色链路依赖**两个** Qwen3-TTS 模型，缺一不可：

| 模型 | 作用 | 放到 |
|---|---|---|
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | **生成**参考音色（按需"设计"声线，绕过找素材） | `<root>/Qwen3-TTS-12Hz-1.7B-VoiceDesign/` |
| `Qwen3-TTS-12Hz-0.6B-Base` | **实际朗读**（快，跑推理的就是它） | `<root>/Qwen3-TTS-12Hz-0.6B-Base/` |

两者均 `license: apache-2.0`。官方提供的入口：
HF `Qwen/qwen3-tts` collection / ModelScope `Qwen/Qwen3-TTS` collection。

为什么这么绕：**1.7B 的 VoiceDesign 只能"设计"，不能拿来跑实时朗读**，而 0.6B 承担
实际合成。做法是让 1.7B 按描述生成一段参考音频，再把这段喂给 0.6B 做音色克隆。

关于这条路的效果边界，有两点实测结论值得记：

- **VoiceDesign 的设计意图不被 0.6B 继承。** seed 造成的差异（~79Hz）大于不同描述
  之间的差异（~49Hz），也就是说克隆环节相当于重新掷骰子。所以正确做法不是写更好的
  描述，而是**批量生成候选再人工挑**——见 `ctest/batch_candidates.py`。
- **参考音频传音色，不传发音/咬字**，口型和吐字质量由文本侧决定。

## 参考音色

`models/speaker_refs/` 下是一段很短的参考音频，决定成品声线的"音色层"。

- `voicedesign_D_anime.wav`：当前使用，由 1.7B VoiceDesign 生成。
- `kokoro_zf_xiaoyi.wav`：备选，来自 Kokoro 的 `zf_xiaoyi`（Apache-2.0）。

**这两条更适合当作"配方"而不是"文件"来分享。** 仓库里可以记录生成参数（描述文本、
seed、pitch），因为真正可复现的是参数；音频本身是几秒的二进制，且它是**声纹**——
一段能直接克隆出某把嗓子的素材，传播医学 transformed audio 本身就有伦理负担。

## Live2D 角色

**这一项请按"不可分发"处理，比上面所有条目都严格。**

`Open-LLM-VTuber/live2d-models/shufulei/`（以及源目录 `舒芙蕾/`）不在发布范围内。
原因不是体积：VTube Studio 导出的模型带有**各自的授权条款**，常见条款明确
禁止二次分发、转售、以及用作 AI 训练数据。它是你个人的角色美术资产。

建议这样拆：

- **发布**：接入方法——`model3.json` 要怎么补 `Motions` / `Expressions` / `HitAreas`，
  情感数组与 `model_dict.json` 数字索引的对应关系，中性复位表情为什么要自己造。
  这部分是通用知识，对所有 Cubism 3~5 模型都有用，也是真正有价值的东西。
- **不发布**：`.moc3`、纹理、`.motion3.json`、`.exp3.json` 等美术资源本身。

在 README 里放一句"自备模型 + 按上面的方法接入"就够了，不必附上任何美术资源。
