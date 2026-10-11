#!/usr/bin/env python3
"""Live-stream danmaku -> Open-LLM-VTuber bridge.

Why this exists
---------------
The VTuber backend exposes one WebSocket (`ws://127.0.0.1:12393/client-ws`) that
accepts `{"type":"text-input","text":"..."}`.  Anything that can emit that JSON
is a valid input source, so platform-specific danmaku scraping stays *outside*
the main pipeline -- switching platform never touches the model, TTS or Live2D.

Three problems a naive "forward every message" bridge has, all observed:

1. Throughput mismatch.  A round costs ~7-8 s end to end (TTS dominates), so the
   ceiling is ~8 replies/minute.  A mid-size room produces 10-50 danmaku/minute.
   Queuing everything means the AI is always 5 minutes behind and answers
   questions nobody remembers asking.  Per the user's call: **while the AI is
   busy, incoming danmaku are dropped on the floor, not queued.**

2. The backend waits forever.  `finalize_conversation_turn()` calls
   `wait_for_response(client_uid, "frontend-playback-complete")` with
   `timeout=None` -- no timeout.  A headless bridge that never sends it leaves
   the conversation chain hanging, so the next `text-input` is not processed
   cleanly.  The bridge must answer that handshake.

3. Most danmaku are noise.  Repeated chars, single chars, "666", links.  Each
   one costs a 7 second TTS round.  Scoring filters them before they ever reach
   the model.

Sources (`--source`)
--------------------
  http      -- POST /danmaku {"user","text","kind"} on `--port`.
               Platform-agnostic: a userscript in the browser forwards what the
               page already renders.  Works on any platform with a web chat.
  stdin     -- one danmaku per line (JSON or plain text).  For testing.
  bilibili  -- blivedm direct WebSocket (room id only, no API key).

Every source ALSO serves the intake endpoints (POST /danmaku, GET /stats,
WS /inject) on `--port`, because WS /inject is how the Live2D page attaches and
the page's socket is the only one the audience can hear.  See run_intake_server.

Usage
-----
    python ctest/danmaku_bridge.py --source http --port 8765
    python ctest/danmaku_bridge.py --source stdin        # type danmaku, see gating
    python ctest/danmaku_bridge.py --source bilibili --room-id 12345

Before trusting bilibili, run ctest/blive_probe.py <room_id>: it tells you
whether your network can even reach B站's danmaku APIs (they answer code -352
to many datacenter/office IPs), instead of leaving you staring at silence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

# Any local WS traffic must bypass the corporate/CLI proxy, or the connection
# dies with "CONNECT 502" before it is established.
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # websockets < 13
    from websockets.legacy.client import connect as ws_connect  # type: ignore

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --------------------------------------------------------------------------- #
# danmaku model
# --------------------------------------------------------------------------- #

@dataclass
class Danmaku:
    user: str
    text: str
    kind: str = "chat"      # chat | gift | guard
    ts: float = field(default_factory=time.time)


GIFT_KINDS = {"gift", "guard", "superchat", "sc"}

# Asking the AI something -> worth answering.  Plain chatter -> usually not.
QUESTION_HINTS = ("吗", "呢", "?", "？", "怎么", "为什么", "是谁", "什么", "哪", "几", "能不能", "可以", "会不会")

# Marks of a low-information message: mostly one repeated char, or pure symbols.
_JUNK_RE = re.compile(r"^[\s\W_0-9]+$", re.UNICODE)
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\S+")


def normalize(text: str) -> str:
    """Collapse whitespace and duplicated chars so '哈哈哈' == '哈哈哈哈哈'."""
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)
    return t.casefold()


def is_spam(text: str) -> bool:
    """True when a message is one character repeated into noise.

    This must run on the RAW text: `normalize()` collapses runs of identical
    chars first, so '哈哈哈哈哈' would otherwise arrive here as '哈哈' and look
    perfectly fine.  Real-world casualty of getting that wrong: the model reads
    a laugh out loud and burns a 7 second TTS round on it.
    """
    t = re.sub(r"\s+", "", text)
    if len(t) < 2:
        return True
    counts = Counter(t)
    top, n = counts.most_common(1)[0]
    # '可以可以' has 2 repeats of 2 chars -> kept. '哈哈哈哈哈' -> dropped.
    return n >= 3 and n / len(t) >= 0.6


def score(d: Danmaku, character_name: str) -> int:
    """Higher = more worth spending a 7-second TTS round on. <=0 means drop."""
    raw = d.text.strip()
    if not raw:
        return -1

    if d.kind in GIFT_KINDS:
        return 100

    body = _MENTION_RE.sub("", raw).strip()
    norm = normalize(body)

    if len(norm) < 2:
        return -1
    if _URL_RE.search(body):
        return -1
    if _JUNK_RE.match(norm) or is_spam(body):
        return -1

    s = 30
    if any(h in body for h in QUESTION_HINTS):
        s += 30
    if character_name and character_name in body:
        s += 20
    # Longer = more likely a real question, but cap it: length is latency.
    s += min(len(body) // 10, 10)
    return s


# --------------------------------------------------------------------------- #
# bridge
# --------------------------------------------------------------------------- #

async def _safe_send(ws, obj: dict) -> None:
    """await ws.send(json) without letting a dead socket raise anywhere."""
    try:
        await ws.send(json.dumps(obj))
    except Exception:
        pass


class Bridge:
    """Owns one backend WebSocket and decides which danmaku are worth sending."""

    def __init__(
        self,
        ws_url: str,
        character_name: str = "米粒",
        window: float = 1.0,
        user_cooldown: float = 20.0,
        busy_timeout: float = 60.0,
        max_chars: int = 40,
        verbose: bool = True,
    ):
        self.ws_url = ws_url
        self.character_name = character_name
        self.window = window
        self.user_cooldown = user_cooldown
        self.busy_timeout = busy_timeout
        self.max_chars = max_chars
        self.verbose = verbose

        self.busy = False
        self.busy_since = 0.0
        self.round = 0

        # The browser page renders the character AND plays the audio.  The
        # backend does NOT broadcast: a reply goes only to the connection that
        # asked (verified by ctest/test_cross_client.py).  So a headless bridge
        # that opens its own socket is invisible and silent -- the audience
        # sees a frozen model and hears nothing.
        #
        # Fix: inject a script into the page that captures the page's own
        # WebSocket and forwards our danmaku through it.  `self.page` is that
        # channel; when it is absent we can only talk to our own socket.
        self.page = None

        self._pending: list[tuple[int, Danmaku]] = []   # (score, item)
        self._flushing: Optional[asyncio.Task] = None
        self._last_by_user: dict[str, float] = {}
        self._recent: deque[str] = deque(maxlen=30)

        self.stats = {"received": 0, "dropped_noise": 0, "dropped_dup": 0,
                      "dropped_cooling": 0, "dropped_busy": 0,
                      "dropped_no_page": 0, "sent": 0}

    # ---------- logging ----------

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    # ---------- intake ----------

    def submit(self, d: Danmaku) -> None:
        """Called by whatever source is running.  Never blocks on the network."""
        self.stats["received"] += 1

        s = score(d, self.character_name)
        if s <= 0:
            self.stats["dropped_noise"] += 1
            return

        if self.page is None:
            # Nobody is watching/hearing.  Sending would burn a TTS round into
            # a socket no audience can perceive.
            self.stats["dropped_no_page"] += 1
            return

        # Busy => hard drop.  This is the deliberate choice: a 5-minute-deep
        # queue answers stale questions, which is worse than answering none.
        if self.busy:
            self.stats["dropped_busy"] += 1
            return

        now = time.time()
        last = self._last_by_user.get(d.user, 0.0)
        if now - last < self.user_cooldown:
            self.stats["dropped_cooling"] += 1
            return

        norm = normalize(d.text)
        if norm in self._recent:
            self.stats["dropped_dup"] += 1
            return

        self.log(f"in  <{d.user}> {d.text}  (score {s})")
        self._pending.append((s, d))            # type: ignore[arg-type]
        if self._flushing is None or self._flushing.done():
            self._flushing = asyncio.ensure_future(self._flush())

    async def _flush(self) -> None:
        """Wait one short window, then send only the best danmaku of the batch."""
        await asyncio.sleep(self.window)
        if not self._pending:
            return
        if self.busy:
            # Was a bare `return`: the whole batch vanished with no counter and
            # no log line, so danmaku disappeared between "received" and "sent"
            # with nothing to point at. Count them.
            n = len(self._pending)
            self.stats["dropped_busy"] += n
            self._pending = []
            self.log(f"busy: dropped whole batch of {n}")
            return
        scored = sorted(self._pending, key=lambda x: -x[0])
        self._pending = []
        best: Danmaku = scored[0][1]

        text = _MENTION_RE.sub("", best.text).strip()
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
        if len(scored) > 1:
            self.log(f"batch: kept 1 of {len(scored)} (dropped {len(scored)-1})")

        self._last_by_user[best.user] = time.time()
        self._recent.append(normalize(best.text))
        await self.send(text)

    # ---------- backend conversation ----------

    # ---------- page channel ----------

    def on_msg(self, obj: dict) -> None:
        """One decoded message from the attached page."""
        if obj.get("ping"):
            # Answer the page's keep-alive. Traffic both ways is what stops
            # Chrome from throttling and eventually freezing a background tab,
            # and a stalled keepalive is how we notice when it happens anyway.
            if self.page is not None:
                asyncio.ensure_future(_safe_send(self.page, {"pong": True}))
            return
        ev = obj.get("event")
        if ev:
            self.on_page_event(ev)
        elif obj.get("hello"):
            self.log("page handshake ok")

    def attach_page(self, ws) -> None:
        self.page = ws
        self.log("page connected -- danmaku will go through the browser")

    def detach_page(self) -> None:
        self.page = None
        self.log("page disconnected -- danmaku will be dropped until it returns")

    def on_page_event(self, event: str) -> None:
        """Busy/idle comes from the page, because that is where replies land."""
        if event == "conversation-chain-end":
            dt = time.time() - self.busy_since if self.busy_since else 0
            self.busy = False
            self.log(f"idle again (round took {dt:.1f}s)")
        elif event == "backend-synth-complete":
            pass  # audio is queued; the chain ends later

    async def send(self, text: str) -> None:
        if self.page is None:
            self.log("send failed: no page connected")
            return
        self.busy = True
        self.busy_since = time.time()
        self.round += 1
        self.stats["sent"] += 1
        self.log(f"OUT -> {text}")
        # The page injects this into its own backend socket.
        await self.page.send_str(json.dumps({"send": text}))

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with ws_connect(self.ws_url, open_timeout=15) as ws:
                    self._ws = ws
                    backoff = 1.0
                    self.log(f"connected to {self.ws_url}")
                    await ws.recv()  # connection-established ack
                    await self._pump(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log(f"backend disconnected ({type(e).__name__}: {e}); "
                         f"retry in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 15)

    async def _pump(self, ws) -> None:
        while True:
            raw = await ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await self._on_message(ws, msg)

    async def _on_message(self, ws, msg: dict) -> None:
        mtype = msg.get("type")

        # The backend blocks the conversation chain on this and has NO timeout.
        # A headless bridge must answer it or every later turn stacks up.
        if mtype == "backend-synth-complete":
            await ws.send(json.dumps({"type": "frontend-playback-complete"}))
            return

        if mtype == "control" and msg.get("text") == "conversation-chain-end":
            dt = time.time() - self.busy_since if self.busy_since else 0
            self.busy = False
            self.log(f"idle again (round took {dt:.1f}s)")
            return

        if mtype == "full-text" and msg.get("text"):
            self.log(f"ai  : {msg['text']}")
            return

        if mtype == "error":
            self.log(f"ERROR from backend: {msg}")

    async def watchdog(self) -> None:
        """If a round never finishes, stop treating the AI as busy forever."""
        while True:
            await asyncio.sleep(2)
            if self.busy and time.time() - self.busy_since > self.busy_timeout:
                self.log(f"busy timeout after {self.busy_timeout:.0f}s -- "
                         f"forcing idle (round may have failed)")
                self.busy = False


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #

async def source_stdin(bridge: Bridge) -> None:
    """One danmaku per line: JSON {"user","text","kind"} or plain text."""
    loop = asyncio.get_running_loop()
    print("stdin source ready -- type danmaku, Enter to submit, Ctrl-D to stop",
          flush=True)
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            await asyncio.sleep(0.3)
            continue
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
                bridge.submit(Danmaku(user=obj.get("user", "viewer"),
                                      text=obj.get("text", ""),
                                      kind=obj.get("kind", "chat")))
                continue
            except Exception:
                pass
        bridge.submit(Danmaku(user="viewer", text=line))


async def run_intake_server(bridge: Bridge, port: int) -> None:
    """The always-on local endpoint set: page attaches here, any platform can POST here.

    Routes:
      POST /danmaku   one danmaku (or a JSON list of them)
      GET  /stats     counters
      GET  /inject    WebSocket used by the injected page script

    IMPORTANT: this runs for EVERY source, including `--source bilibili`.
    It used to live inside the http source, which meant that running the
    bilibili source left no `/inject` route for the Live2D page to attach to,
    `bridge.page` stayed None, and every single danmaku landed in
    `dropped_no_page` -- the AI said nothing at all while the logs looked calm.
    """
    from aiohttp import web, WSMsgType

    async def inject(req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        # Only one page can be the one the audience watches. If several tabs
        # attach (or one reloads), the newest wins -- so this must be logged,
        # otherwise the loser silently waits forever for replies that go to the
        # winner and the symptom reads as "the AI is broken".
        if bridge.page is not None:
            bridge.log("second page attached -- replacing the previous one")
        bridge.attach_page(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    obj = json.loads(msg.data)
                except Exception:
                    continue
                bridge.on_msg(obj)
        finally:
            # RACE, and it cost 50 seconds of live silence: an old socket that
            # closes *after* a new one has attached used to clear the shared
            # `bridge.page`, detaching the connection that was actually alive.
            # Every danmaku then landed in `dropped_no_page` while /stats and
            # the logs looked calm. Only the owner may detach.
            if bridge.page is ws:
                bridge.detach_page()
            else:
                bridge.log("stale page socket closed -- leaving current one up")
        return ws

    # Access-Control-Allow-Private-Network is the one that actually matters for
    # the userscript path: live.bilibili.com is a *public* origin and 127.0.0.1
    # is localhost, so Chrome runs a Local Network Access preflight. Without
    # this header the preflight fails and the fetch never settles -- it neither
    # resolves nor rejects, so the collector just silently posts nothing while
    # looking perfectly healthy. Page-local (localhost -> localhost) requests
    # are exempt, which is why testing from :12393 always worked and hid this.
    CORS = {"Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Private-Network": "true"}

    async def post(req):
        try:
            obj = await req.json()
        except Exception:
            return web.Response(status=400, text="bad json",
                                headers=CORS)
        if isinstance(obj, list):
            items = obj
        else:
            items = [obj]
        for it in items:
            bridge.submit(Danmaku(user=str(it.get("user", "viewer")),
                                  text=str(it.get("text", "")),
                                  kind=str(it.get("kind", "chat"))))
        return web.Response(text="ok", headers=CORS)

    async def options(req):          # CORS preflight from the browser
        return web.Response(status=204, headers=CORS)

    async def stats(req):
        return web.json_response({**bridge.stats, "busy": bridge.busy,
                                  "page": bridge.page is not None})

    app = web.Application()
    app.router.add_post("/danmaku", post)
    app.router.add_options("/danmaku", options)
    app.router.add_get("/stats", stats)
    app.router.add_get("/inject", inject)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    print(f"intake ready -- POST http://127.0.0.1:{port}/danmaku "
          f'{{"user":"a","text":"hi"}}  |  GET /stats  |  WS /inject', flush=True)
    while True:
        await asyncio.sleep(3600)


async def source_http(bridge: Bridge, port: int) -> None:
    """Compatibility name: the intake server *is* the http source."""
    await run_intake_server(bridge, port)


async def load_cookie_file(path: str) -> dict[str, str]:
    """`k=v; k=v` file -> dict. Same format as what cookie_export.js prints."""
    jar: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        print(f"[bili] cannot read cookie file {path}: {e}", flush=True)
        return jar
    for part in raw.replace("\n", ";").split(";"):
        item = part.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar


async def source_bilibili(bridge: Bridge, room_id: int, sessdata: str = "",
                          cookie_file: str = "") -> None:
    """Direct BiliBili WebSocket via blivedm -- room id + browser cookies.

    Install (brotli is pinned to a version with no wheel, so bypass it):
        uv pip install --python .venv/Scripts/python.exe --only-binary :all: brotli
        uv pip install --python .venv/Scripts/python.exe --no-deps blivedm

    About the cookies: the two token APIs answer `code=-352` for anonymous
    callers. That code reads like "your IP is banned" but supplying real browser
    cookies often clears it outright (measured: getInfoByRoom went -352 -> 0
    with nothing but buvid3/b_nut). So cookies are the FIRST thing to try, not
    a last resort. Export them with ctest/cookie_export.js and pass the file
    here. The blivedm route needs no browser tab open while you stream, which
    makes it strictly better than the DOM userscript when it works.

    Why this wrapper exists instead of just `client.start()`:
      blivedm's network coroutine RAISES when `init_room()` fails (typically
      the two web-room APIs returning code -352 -- B站 IP 风控), and then sets
      `self._network_future = None` and returns.  Nothing else in the library
      notices.  The naive caller loops `await asyncio.sleep(1)` forever, so the
      process stays alive, logs look clean, and ZERO danmaku ever arrive.
      That failure mode is indistinguishable from "quiet room", which wastes
      an entire debugging session.  So we watch the client's own state and
      rebuild it loudly.
    """
    try:
        import aiohttp
        from blivedm import BLiveClient, BaseHandler
    except ImportError as e:
        print(f"bilibili source unavailable ({e}). Install with:\n"
              "  uv pip install --python .venv/Scripts/python.exe "
              "--only-binary :all: brotli\n"
              "  uv pip install --python .venv/Scripts/python.exe --no-deps blivedm",
              flush=True)
        return

    seen_pkts = {"n": 0}          # raw packets from this room, before filtering

    jar: dict[str, str] = {}
    if cookie_file:
        jar = await load_cookie_file(cookie_file)
        if jar:
            names = ", ".join(sorted(jar))
            print(f"[bili] using {len(jar)} cookies: {names}", flush=True)
    if sessdata:                  # still honoured: one-off override
        jar["SESSDATA"] = sessdata

    class Handler(BaseHandler):
        async def _on_danmaku(self, client, message):
            seen_pkts["n"] += 1
            bridge.submit(Danmaku(user=message.uname, text=message.msg,
                                  kind="chat"))

        async def _on_gift(self, client, message):
            seen_pkts["n"] += 1
            bridge.submit(Danmaku(user=message.uname,
                                  text=f"{message.uname} 送出 "
                                       f"{message.num} 个{message.gift_name}",
                                  kind="gift"))

        async def _on_buy_guard(self, client, message):
            seen_pkts["n"] += 1
            bridge.submit(Danmaku(user=message.username,
                                  text=f"{message.username} 上了舰长",
                                  kind="guard"))

        async def _on_super_chat(self, client, message):
            seen_pkts["n"] += 1
            bridge.submit(Danmaku(user=message.uname, text=message.message,
                                  kind="superchat"))

    async def one_life() -> str:
        """Run one BLiveClient until it breaks.  Return why, so we can say it."""
        session = None
        client = None
        try:
            if jar:
                session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10), cookies=jar)
            client = BLiveClient(room_id, session=session, ssl=True)
            client.add_handler(Handler())
            client.start()

            started = time.time()
            warned_no_ws = False
            warned_silent = False
            while True:
                await asyncio.sleep(1)

                # Private attrs, but they are the only observable difference
                # between "connected" and "quietly dead" in this library.
                task = getattr(client, "_network_future", None)
                if task is None:
                    return ("blivedm 网络协程已退出 —— 几乎肯定是 init_room() 失败"
                            "（B站 web-room API 返回 code -352 表示出口 IP 被风控）")

                ws = getattr(client, "_websocket", None)
                elapsed = time.time() - started

                # Give it 25s to establish before calling it broken.
                if ws is None and elapsed > 25 and not warned_no_ws:
                    warned_no_ws = True
                    print(f"[bili] 警告：{elapsed:.0f}s 仍未建立弹幕 WebSocket —— "
                          f"房间号对不对？网络出口是否被风控？", flush=True)

                # Once connected, silence just means a quiet room; say so, then
                # keep going instead of tearing anything down.
                if ws is not None and elapsed > 60 and not warned_silent \
                        and seen_pkts["n"] == 0:
                    warned_silent = True
                    print("[bili] WebSocket 已连接，但 60s 内没有收到任何弹幕。"
                          "  如果直播间确实有人说话，检查房间号是否正确。",
                          flush=True)
        finally:
            if client is not None:
                try:
                    await client.stop_and_close()
                except Exception:
                    pass
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    pass

    attempt = 0
    while True:
        attempt += 1
        print(f"[bili] connecting to room {room_id} (attempt {attempt})",
              flush=True)
        reason = await one_life()
        backoff = min(5 * attempt, 60)
        print(f"[bili] 断开：{reason} —— {backoff}s 后重连", flush=True)
        await asyncio.sleep(backoff)


# --------------------------------------------------------------------------- #

async def amain(args) -> None:
    bridge = Bridge(
        ws_url=args.ws,
        character_name=args.character,
        window=args.window,
        user_cooldown=args.cooldown,
        busy_timeout=args.busy_timeout,
        max_chars=args.max_chars,
    )
    # The intake server runs for EVERY source.  It carries /inject, which is
    # how the Live2D page attaches; without it the bridge has no way to reach
    # the audience and every danmaku is dropped as dropped_no_page.
    tasks = [asyncio.ensure_future(bridge.run()),
             asyncio.ensure_future(bridge.watchdog()),
             asyncio.ensure_future(run_intake_server(bridge, args.port))]

    if args.source == "stdin":
        tasks.append(asyncio.ensure_future(source_stdin(bridge)))
    elif args.source == "bilibili":
        if not args.room_id:
            print("--source bilibili requires --room-id", flush=True)
            return
        tasks.append(asyncio.ensure_future(
            source_bilibili(bridge, args.room_id, args.sessdata,
                            args.cookie_file)))
    # http: the intake server already accepts it.

    async def report():
        while True:
            await asyncio.sleep(30)
            st = bridge.stats
            print(f"[stats] recv={st['received']} sent={st['sent']} "
                  f"noise={st['dropped_noise']} dup={st['dropped_dup']} "
                  f"cooling={st['dropped_cooling']} busy_dropped={st['dropped_busy']}",
                  flush=True)

    tasks.append(asyncio.ensure_future(report()))
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["http", "stdin", "bilibili"],
                   default="http")
    p.add_argument("--ws", default="ws://127.0.0.1:12393/client-ws")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--room-id", type=int, default=0)
    p.add_argument("--sessdata", default="",
                   help="deprecated: prefer a cookie file with everything in it")
    p.add_argument("--cookie-file", default="",
                   help="browser cookies from ctest/cookie_export.js -- often "
                        "clears code -352 and lets the direct route work")
    p.add_argument("--character", default="米粒",
                   help="character name; danmaku mentioning it rank higher")
    p.add_argument("--window", type=float, default=1.0,
                   help="collect danmaku this long before picking one")
    p.add_argument("--cooldown", type=float, default=20.0,
                   help="per-user cooldown in seconds")
    p.add_argument("--busy-timeout", type=float, default=60.0,
                   help="force idle if a round never completes")
    p.add_argument("--max-chars", type=int, default=40,
                   help="truncate before TTS; chars are latency")
    args = p.parse_args()

    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
