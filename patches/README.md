# llama.cpp fork：我们改了什么，以及历史在哪

`llama.cpp/` 是本项目的 CPU 特化 fork，也是这个仓库里技术含量最高的部分。
它是上游 llama.cpp 的快照 + 我们的魔改，不是第三方依赖。

## 上游基线

| 项 | 值 |
|---|---|
| 上游项目 | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)（MIT） |
| 基线 commit | `5096f2a42468daff7ff38d97b48bd17432196e98` — *baseline: llama.cpp master (upstream snapshot)* |
| flatten commit | `c649f60` — *flatten: move source to repo root*（把 `llama.cpp-master/` 提到根目录，纯移动，零内容改动） |
| 我们的魔改 | **15 个文件，+1121 / −173 行**，见 `llama-cpp-cpu-tuning.patch` |

要把我们的改动重放到一份干净的上游 checkout 上：

```bash
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
git checkout 5096f2a42468daff7ff38d97b48bd17432196e98
git apply ../patches/llama-cpp-cpu-tuning.patch
```

（patch 里的路径是相对 llama.cpp 根目录的，所以要在该目录里 apply。）

## 为什么 fork 的 `.git` 被改名了

`llama.cpp/.git` 现已改名为 **`llama.cpp/.git.fork-backup/`**。这是发布必需的一步，
不是删历史。

原因是 git 的一条硬行为：目录里只要有 `.git`，外层仓库 `git add` 就会把它当
**嵌套仓库**，只记一个 gitlink 而不记内容——

```
warning: adding embedded git repository: llama.cpp
hint: Clones of the outer repository will not contain the contents of
160000 59a927d...  0    llama.cpp        ← mode 160000，指针而非文件内容
```

后果是 clone 的人拿到一个空目录，而且那个 commit 在任何公共远端都不存在，
`git submodule update` 也救不回来。改名之后 git 不再认为它是仓库，源码就正常入库了。

**恢复完整 fork 历史**（一条命令，随时可做）：

```bash
mv llama.cpp/.git.fork-backup llama.cpp/.git
```

改回来之后 `git log`、`git diff` 照常可用（但此时它又会变回嵌套仓库，别在这状态下
对外层 `git add`）。该目录已被 `.gitignore` 排除，不会进发布包。

## 15 个改动文件，各自对应哪份 spec

| 文件 | 对应 spec |
|---|---|
| `ggml/src/ggml-cpu/ops.cpp`（+741 行，最大头） | `specs/quant-dot-efficiency.md`、`specs/fa-gqa-loop-reorder.md`、`specs/legacy-quant-v-op.md` |
| `ggml/src/ggml-cpu/ggml-cpu.c` / `common.h` / `ops.h` | 同上，配套分派与声明 |
| `ggml/include/ggml.h`、`ggml/src/ggml.c` | 新增算子与类型（如 `ggml_mul_mat_tq`、`GGML_MUL_MAT_TQ_MAX_N/D`） |
| `src/llama-cparams.h`、`llama-model.cpp`、`llama-graph.cpp`、`llama-context.cpp` | `specs/fa-auto-adaptive.md`（新增 `--fa-kv-threshold`、`--fa-max-tokens` 两个开关） |
| `include/llama.h` | 对外暴露上述开关 |
| `common/arg.cpp`、`common.cpp`、`common.h` | 命令行参数接入 |
| `tools/tts/tts.cpp` | Qwen3-TTS 侧的适配 |

想看"为什么这么改"和实测数据，读对应的 spec；想看逐行改动，读 patch。

## 发布边界

- ✅ 发：llama.cpp **源码**（`llama.cpp/` 下 3519 个文件 / 90.4 MB），含 `llama.cpp/LICENSE`（MIT）与 `AUTHORS`
- ❌ 不发：`llama.cpp/build/`（332 MB 编译产物）、`llama.cpp/models/`（74 MB 上游测试 vocab，`.gguf` 属权重）、`*.log`、`.git.fork-backup/`

`build/` 不只是体积问题——它是本项目**隐私命中的唯一来源**：`CMakeCache.txt` 里有
Windows 用户名，`compile_commands.json` 里有 2338 处本机绝对路径。排除它之后，
llama.cpp 源码侧四项隐私扫描（win-user / abs-root / sessdata / email）全部 clean。
