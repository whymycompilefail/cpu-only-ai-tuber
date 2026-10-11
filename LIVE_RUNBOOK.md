# 开播 Runbook（第二次实测通过版）

这份东西存在的理由很朴素：这条链路上有若干个失败模式是**静默的**——进程活着、日志干净、没有任何报错，但米粒就是不开口。靠"看一眼感觉没问题"是查不出来的，所以下面每一步都配了验证命令和**期望输出**，照着比对就行。

日期：2026-10-06。实测结论：真实弹幕 → 米粒说话，一轮 15～32 秒正常收尾。

---

## 0. 架构：谁连谁

先把这张图看明白，后面所有排查都是在确认某一条连线通不通。

```
  B站直播间标签页                         Live2D 标签页 (:12393)
  https://live.bilibili.com/<房间>        http://localhost:12393
        │                                        │
        │ MutationObserver                       │ 被 danmaku_inject.js
        │ 读 data-uname / data-danmaku           │ 劫持了页面自己的 WebSocket
        ▼                                        │
  采集队列（页面变量，不发包）                     │
        │                                        │
        │ CDP Runtime.evaluate                   │ ws://127.0.0.1:8765/inject
        │ (Python 主动取)                         │ ← page=true 就是这条
        ▼                                        ▼
   danmaku_pump.py  ──POST──▶      danmaku_bridge.py (:8765)
   (无代理 opener)                        │
                                          │ ws://127.0.0.1:12393/client-ws
                                          │ 借页面的那条连接发 text-input
                                          ▼
                                   VTuber 后端 (:12393)
                                          │
                            ┌─────────────┴─────────────┐
                            ▼                           ▼
                    llama-server (:8099)         Qwen3-TTS
                    Qwen3.5-2B Q4_K_M
```

**两条必须记住的事实：**

1. **后端不广播。** 回复只发给提问的那条 WebSocket。所以桥接自己开一条连接是没用的——没人听得到。必须借 Live2D 页面那条 socket，这就是 `/inject` 通道和 `page=true` 的意义。
2. **页面绝不能自己发 HTTP。** `https://live.bilibili.com` 到 `http://127.0.0.1` 被 Chrome 的 Local Network Access 拦死。见 §6，别再试着"修复"它了。

---

## 1. 一次性准备（首次）

### 1.1 浏览器 profile

```bash
Open-LLM-VTuber/.venv/Scripts/python.exe ctest/edge_cdp.py \
    --profile C:/temp/vtuber-edge --wait
```

**必须用独立 profile，且路径不能含中文。** 用默认 profile 时 CDP 端口死活不开——四种组合都试过：默认 profile 不开端口，显式传 `--user-data-dir=<默认路径>` **照样不开**。Chromium 是按路径的**值**判断的，不是按有没有传这个开关。

Edge 起来后（默认最小化，看不见是正常的）：

```bash
Open-LLM-VTuber/.venv/Scripts/python.exe ctest/cdp_focus.py bring
```

### 1.2 扫码登录 B 站（**必需，不是可选**）

在这台 profile 里打开直播间并扫码。

**游客拿不到弹幕**：匿名状态下聊天区不加载，`.chat-items` 恒为空、页面写着「登录后可参与讨论」——外观上跟采集器坏了完全一样。曾经据此误判过一次。

登录态存在 profile 里，不用重复扫。验证：

```bash
Open-LLM-VTuber/.venv/Scripts/python.exe ctest/cdp_peek.py
# 期望：chat_items_kids > 0，body_has_login_prompt = False
```

> 不要把 profile 复制走。Edge 会重写 `Local State` 重新生成 AppBound 密钥，复制出来的那份 cookie 全部作废。

---

## 2. 每次开播：按顺序起四个东西

### 步骤 A —— 无界面的三个服务

起 `llama-server :8099` + `后端 :12393` + `桥接 :8765`。默认 `--source http`（走 bilibili 路线会被拒绝，见 §6）。

> **怎么跑，取决于承载它的那个调用**（这条适用于下面每一步，别只看单独的这条命令）。
>
> 决定生死的是**启动它的那次调用本身**是否还活着，而不是命令里有没有 `&`。实测（2026-10-06）：
>
> - 把 `start_live.sh` 当作**后台任务**执行时，它内部用 `&`+`disown` 起的三个进程**全部存活**（llama / 后端 / 桥接都在）。
> - 让它作为一次普通的前台调用跑完就返回，子进程会被回收。
>
> 所以最稳的写法是始终用后台任务，需要时加 `--wait` 让它永不返回：
>
> ```bash
> bash ctest/start_live.sh --wait
> ```
>
> 单独依靠 `&`、`disown`、`nohup`、或者 `DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP` 都不保证奏效。

验证：

```bash
curl -s --noproxy '*' http://127.0.0.1:8099/health   # 期望含 "status"
curl -s --noproxy '*' -o /dev/null -w '%{http_code}\n' http://127.0.0.1:12393/   # 200
curl -s --noproxy '*' http://127.0.0.1:8765/stats     # 期望是 JSON
```

> **`--noproxy` 每次都要。** 这台机器有系统代理且**不绕过 loopback**，不加会返回 502，看起来像服务挂了。

### 步骤 B —— Edge（CDP）

```bash
Open-LLM-VTuber/.venv/Scripts/python.exe ctest/edge_cdp.py \
    --profile C:/temp/vtuber-edge --wait
```

验证：

```bash
curl -s --noproxy '*' http://127.0.0.1:9222/json/version
# 期望：出现 "Browser": "Edg/..."
```

> **保活**：在这个环境里 `&`、`disown`、`nohup`、`DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP` **全部无效**——三种写法依次失败过。唯一可行是把这条命令当作**后台任务**执行，`--wait` 让它永不返回。

### 步骤 C —— Live2D 标签页（直播姬要抓的窗口）

必须先于或独立于 pump 打开：

```bash
curl -s --noproxy '*' -X PUT "http://127.0.0.1:9222/json/new?http://localhost:12393"
```

等 6～10 秒，然后看**握手**：

```bash
curl -s --noproxy '*' http://127.0.0.1:8765/stats
# 期望： "page": true
```

`page` 就是唯一要盯的指标。**`false` = 米粒一定不会开口**，不管别的多正常。

如果仍然是 `false`，抓页面 console：

```bash
Open-LLM-VTuber/.venv/Scripts/python.exe ctest/cdp_console.py 12393 20
# 期望看到：[danmaku-inject] page websocket captured
#           [danmaku-inject] bridge connected
```

### 步骤 D —— 弹幕泵

```bash
Open-LLM-VTuber/.venv/Scripts/python.exe ctest/danmaku_pump.py \
    --room-id $BILI_ROOM_ID --interval 1.0
```

（同样走后台任务。）它会自动找到/打开直播间标签页并安装采集器。启动后立刻有一行：

```
[pump] chat pane: {"kids":10,"login_wall":false}
```

`kids` 是聊天区已有弹幕条数。`login_wall: true` 或 `kids: 0` ⇒ 没登录，回去重做 §1.2。

> 泵是会自己复原的：CDP socket 断了会退避重连，标签页导航走了会重装采集器。别因为它报一行 `session ended` 就急着重启——28 分钟后的那次崩溃修的就是这个。

---

## 3. 验收

### 3.1 L0：联合穿刺（不依赖 B 站）

还没到这一步就该做：直接 POST 一条给桥接。

```bash
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/danmaku \
     -H 'Content-Type: application/json' \
     -d '{"user":"端到端测试","text":"米粒你好呀，你是谁？"}'
```

然后看 `round took`：

```bash
grep -v '^\[stats\]' ctest/danmaku_bridge.log | tail -8
```

**这一层的意义**：先证明「桥接 → 米粒」这一段是好的，再去碰 B 站。第一次实测之所以失败，就是因为跳过了分层，四件事一起上，出问题时不知道是谁的锅。

期望日志：

```
in <端到端测试> 米粒你好呀，你是谁？ (score NN)
OUT -> ... → idle again (round took 15.3s)
```

> 必须是 `idle again (round took Xs)`，**不能是** `busy timeout`。后者是看门狗强行解锁，说明一轮没跑完。
>
> 健康的一轮是 **15～32 秒**（TTS 占绝大部分）。

#### 已知的坑：冷启动的前几轮会超，别急着下结论

2026-10-06 从零复现时实测到这个序列：

```
第一批（起栈后首批弹幕）  busy timeout after 60s
第二轮                   idle again (round took 118.6s)
第三轮（间隔充足）        idle again (round took 15.3s)   <- 健康值
第四轮（紧接着上一轮）    idle again (round took 64.3s)
```

**单次投递、间隔充足时是健康的 15.3s**；连着快投就会被拖长。原因是后端一轮没真正收尾时，它的 `conversation-chain-end` 会延后，和下一轮的开始发生交错——桥接收到的"完成"信号对应的是上一轮。据此会导致 `round took` 虚高，偶尔还能看到桥接把上一轮的答案当成这一轮的。

这不是本文档能修的问题，属于已知待修项。**规避办法：**

- 验收时**一次只投一条，投完等它 idle**，不要连投；
- 刚起栈后第一批弹幕出现 `busy timeout` 是正常现象，不代表链路坏了，**再看下一轮**；
- 真实直播中弹幕间隔远大于一轮耗时，所以这个问题基本不会被触发（这也是第二轮实测体感"非常顺畅"的原因）。

不要把 `busy timeout` 当成绿灯忽略，也不要当成红灯推倒重来——**看下一轮**。

### 3.2 L1：真实弹幕

用自己的号在直播间发一条。**发完之后 pump 日志里出现的必须是真实用户名**（`data-uname`），不是 `viewer`——出现 `viewer` 说明采集器取到了节点但没读到属性。

不想切换账号时可用页面真实输入框代发（注意：会用当前登录的账号真发出去）：

```bash
# 改 ctest/cdp_send_danmaku.js 里的 TEXT 然后：
Open-LLM-VTuber/.venv/Scripts/python.exe \
    ctest/cdp_eval.py "live.bilibili.com" ctest/cdp_send_danmaku.js --await
```

> 它是被 `cdp_eval.py` **注入执行**的一段 JS，本身不是可执行脚本。直接 `python ctest/cdp_send_danmaku.js` 是不行的。

期望 pump 日志：

```
[pump] <ppv500288> 米粒米粒，听得到我说话吗？
```

桥接：

```
in <ppv500288> 米粒米粒，听得到我说话吗？ (score 81)
OUT -> ... → idle again (round took 15.3s)
```

### 3.3 L2：亲耳听到

最后只有耳朵能验收。页面 console 出现 `Speech started` 只代表**开始播放**，不代表扬声器响了。

> 排查静音时别看后端日志——**INFO 级不记 TTS**。「LLM 出句之后日志一片安静」是正常的，不是失败。

---

## 4. 关停

```bash
bash ctest/stop_stack.sh
```

它按端口杀 8099 / 12393 / 8765，外加后端留下的常驻 `llama-tts`。Edge 要另关。

---

## 5. 直播姬

抓 **`http://localhost:12393` 那个标签页**。

直播间标签页可以安心放在后台——弹幕走 WebSocket、DOM 照常变动，CDP 也会强制渲染器保持活跃。两个窗口只能显示一个，而显示出来的必须是 Live2D 那个。

> 注意区分「画面」和「握手」：直播姬只需要它能被抓到像素，而米粒开口只需要 `/stats` 里 `page=true`。这是两个独立条件，别混为一谈。

---

## 6. 已证伪的路线（**别再投入**）

写在这里是因为这些都被认真试过、且失败方式是**静默**的。

### blivedm 直连：`getDanmuInfo` 恒 -352

带真实 cookie 后 `getInfoByRoom` 返回 `code=0`（IP 没封、登录态有效），但 `getDanmuInfo` 恒 `-352`。试了 5 种组合全一样：默认 UA / 加 Referer / 真实 Edge UA + Origin / 去掉 `type` / 加 `wts`。**既不是 cookie 不全，也不是缺 WBI 签名。** `start_live.sh` 里 `bilibili` 这个 source 已被告知如何处理。

### 页面直接 `fetch()` 到 loopback：不可能

判别链条（重要的方法论，别重跑）：

| 实验 | 结果 | 排除了什么 |
|---|---|---|
| 桥接加 `Access-Control-Allow-Private-Network`；curl 模拟 Chrome 的预检 | `204` + 头齐全 | 服务端响应是对的 |
| 页面发 `text/plain` POST（CORS 简单请求，**根本不触发预检**） | 超时 | **不是预检问题** |
| fetch 的 Promise 既不 resolve 也不 reject | 悬空 | CORS 失败会立刻 reject ⇒ **不是 CORS** |
| `--proxy-bypass-list` | 无效 | 系统走 PAC 脚本，bypass 列表不适用 |
| `--no-proxy-server` | 无效 | 不是代理 |

公共 https origin 访问 loopback 被 Chrome 的 Local Network Access 挡住，请求直接悬空，**没有任何报错可查**。

所以架构改成：页面只做它独一无二能做的事（渲染 B 站已经推给它的聊天），联网全交给 Python。`danmaku_collector.js` 因此**不做任何网络请求**。

顺带一提：因为页面不再碰 loopback，`edge_cdp.py` 里那些为打通网络加的 `--no-proxy-server` / `--disable-web-security` **已经删掉**，现在跑的就是干净参数的浏览器——这才是不用打补丁就能发布的样子。

### 曾经绕的大弯路：一行 prototype 赋值

```js
window.WebSocket.prototype = Native.prototype;   // ← 删掉前就是这个样子
```

严格模式下对 Proxy 赋值 `prototype` 抛 `TypeError`，IIFE 在 `connectBridge()` 之前就中断了。页面看起来完全健康，但从未尝试连 8765。代码里有注释说明为什么不能写回去。

---

## 7. 故障速查

| 症状 | 看什么 | 原因 |
|---|---|---|
| 米粒一言不发，日志平静 | `/stats` 的 `page` | `false` ⇒ 握手没建立（§2 步骤 C）|
| `dropped_no_page` 增长 | `/stats` | 收得到弹幕但没人接 |
| `round took` 忽大忽小，或答案答非所问 | 是否连续快投 | 见 §3.1 的 chain-end 错位：一次只投一条 |
| 起栈后首批弹幕 `busy timeout` | 下一轮是否恢复 | 冷启动现象，看下一轮而不是重来 |
| Live2D 报 `/undefined/undefined.model3.json` 404 | console 里是否有 `Setting up textures for model: shufulei` | 这个 404 是初始化竞态，**模型最终是加载成功的**，别被它带偏 |
| pump 报 `kids:0` / `login_wall:true` | `chat pane:` 那行 | 标签页没登录，聊天区不加载 |
| 米粒安静几十秒后又自己恢复 | inject 的 `KEEPALIVE STALLED` | 后台标签页被节流/冻结 |
| `curl :8765` 返回 502 | 忘了 `--noproxy` | 系统代理不绕过 loopback |
| 服务的日志看似不及时 | 日志的**文件时间** | `run_in_background` 的任务输出不在旧 `.log` 里，要显式重定向才落盘 |
| 所有 phenomenon看起来像服务挂了 | `/health` vs HTTP code | 同上，别拿陈旧日志当现状 |

最后一条值得单独说：曾经对着一个 22 小时前的 `danmaku_bridge.log` 排查了很久，而真正活着的那份输出在后台任务里。日志对不上时，**先查文件时间戳**。
