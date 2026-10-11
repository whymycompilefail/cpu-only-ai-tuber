#!/usr/bin/env python3
"""Does YOUR machine actually reach B站's danmaku feed? Answer before debugging anything else.

    Open-LLM-VTuber/.venv/Scripts/python.exe ctest/blive_probe.py <房间号> [--seconds 30]

Why this exists
---------------
Every failure in the bilibili path looks identical from the outside: zero
danmaku.  But the causes are completely different, and so are the fixes:

  1. `getInfoByRoom` / `getDanmuInfo` answer `{"code":-352}` -- B站 风控 the
     caller's IP.  Very common from office/datacenter/VPN exits.  Fix: another
     network, or use the DOM userscript instead (see below).
  2. Those APIs answer code 0, but the WebSocket handshake never completes.
     Usually token/auth drift in the pinned blivedm version.
  3. Everything connects and still no packets: wrong room id, or nobody is
     talking.

blivedm itself reports none of this usefully: on init failure its network
coroutine just returns, leaving a live process with clean logs.  So we test the
three stages separately and tell you which one broke.

If stage 1/2 fail and you cannot fix the network: use ctest/danmaku_userscript.js
(Tampermonkey) with `--source http` instead.  It reads the chat your own browser
already renders, so it needs no B站 API permission at all.

Trying the logged-in route first: supply your browser cookies and `-352` may
vanish, because that code usually means "no browser fingerprint / no session",
not "this IP is banned".  Export them with ctest/cookie_export.js:

    Open-LLM-VTuber/.venv/Scripts/python.exe ctest/blive_probe.py <room> \\
        --cookie-file ctest/bili_cookie.txt

Start with only the cookies `document.cookie` exposes (no SESSDATA needed --
the anti-bot check mostly wants buvid3/b_nut/b_lsid).  Add SESSDATA only if
that still fails; see ctest/cookie_export.js for how to do it with least risk.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

# Local WS only rides through this script for nothing; keep proxy off 127.0.0.1.
import os
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
INFO_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom"
DANMU_URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"

# -352 = 风控; anything else non-zero is some other server-side refusal.
CODE_HINTS = {
    -352: "出口 IP 被风控（换网络，或改用 DOM 油猴方案）",
    -400: "请求参数错误（房间号格式不对？）",
    19002001: "房间不存在",
    -509: "请求过于频繁",
}


def stage(n: int, title: str) -> None:
    print(f"\n[{n}/3] {title}", flush=True)


def cookies_from_string(raw: str) -> dict[str, str]:
    """Parse a `Cookie:` header value (or the output of cookie_export.js)."""
    jar: dict[str, str] = {}
    for part in (raw or "").replace("\n", ";").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        jar[k.strip()] = v.strip()
    return jar


def load_cookies(args) -> tuple[dict[str, str], str]:
    """Return (jar, provenance) so the report can say what was tried."""
    raw = args.cookie or ""
    src = "--cookie"
    if args.cookie_file:
        try:
            with open(args.cookie_file, encoding="utf-8") as f:
                raw = f.read()
            src = args.cookie_file
        except OSError as e:
            print(f"cannot read cookie file: {e}")
            sys.exit(2)
    jar = cookies_from_string(raw)
    return jar, src


async def probe_http(room_id: int, jar: dict[str, str] | None = None
                     ) -> tuple[bool, list[int], bool]:
    """Stage 1: can we even talk to the room APIs?

    Returns (usable, codes, partial) where `partial` means some call came back
    code=0 -- proof that the IP is NOT banned and the cookies are just thin.
    """
    stage(1, f"HTTP 房间 API 可达性（room_id={room_id}）")
    if jar:
        masked = {k: ("<set>" if v else "<empty>") for k, v in jar.items()}
        print(f"   带 {len(jar)} 个 cookie: {masked}", flush=True)
    else:
        print("   匿名请求（无 cookie）", flush=True)
    import aiohttp
    headers = {"User-Agent": UA, "Referer": "https://live.bilibili.com/"}
    codes: list[int] = []
    ok = True
    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            cookies=jar or None) as s:
        for name, url, params in (
            ("getInfoByRoom", INFO_URL, {"room_id": room_id}),
            ("getDanmuInfo", DANMU_URL, {"id": room_id, "type": 0}),
        ):
            try:
                async with s.get(url, headers=headers,
                                 params=params) as r:
                    data = await r.json(content_type=None)
                    code = data.get("code")
                    msg = data.get("message", "")
                    hint = CODE_HINTS.get(code, "")
                    flag = "OK " if code == 0 else "FAIL"
                    print(f"   {flag} {name}: code={code} message={msg!r} {hint}",
                          flush=True)
                    codes.append(code if isinstance(code, int) else -1)
                    if code != 0:
                        ok = False
            except Exception as e:
                print(f"   FAIL {name}: {type(e).__name__}: {e}", flush=True)
                codes.append(-1)
                ok = False

    # Partial success is the single most informative outcome and it used to be
    # reported as "your IP is banned", which sends people away from the fix.
    if 0 in codes and not ok:
        print("   => 注意：有接口已经 code=0 了，说明**不是** IP 被封，而是这次带的"
              " cookie 还不够。", flush=True)
        print("      用 ctest/cookie_export.js 导出**真实的**浏览器 cookie 再试，"
              "必要时补上 SESSDATA。", flush=True)
        return False, codes, True
    if not ok:
        print("   -> blivedm 直连这条路大概率走不通：它必须先调这两个接口拿 token。",
              flush=True)
        print("   -> 改走 ctest/danmaku_userscript.js（浏览器读 DOM，不需要 B站 API）。",
              flush=True)
    return ok, codes, False


async def probe_live(room_id: int, seconds: float,
                     jar: dict[str, str] | None = None) -> int:
    """Stages 2+3: WS handshake, then actual packets.  Returns danmaku count."""
    stage(2, "WebSocket 握手")
    try:
        from blivedm import BLiveClient, BaseHandler
    except ImportError:
        print("   blivedm 未安装。装法：")
        print("     uv pip install --python Open-LLM-VTuber/.venv/Scripts/python.exe"
              " --only-binary :all: brotli")
        print("     uv pip install --python Open-LLM-VTuber/.venv/Scripts/python.exe"
              " --no-deps blivedm")
        return -1

    got: list[tuple[str, str]] = []

    class H(BaseHandler):
        async def _on_danmaku(self, client, message):
            got.append((message.uname, message.msg))

        async def _on_gift(self, client, message):
            got.append((message.uname,
                        f"[礼物] x{message.num} {message.gift_name}"))

        async def _on_super_chat(self, client, message):
            got.append((message.uname, f"[SC] {message.message}"))

    # Cookies must ride on the token requests too -- otherwise stage 2 repeats
    # stage 1's failure and reports a handshake problem that is really -352.
    session = None
    if jar:
        import aiohttp
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10), cookies=jar)
    client = BLiveClient(room_id, session=session, ssl=True)
    client.add_handler(H())
    client.start()

    connected_at = None
    deadline = time.time() + seconds
    t0 = time.time()
    try:
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            if getattr(client, "_network_future", None) is None:
                print("   FAIL 网络协程已退出 —— init_room() 失败。"
                      "（通常是第 1 步的 API 风控）", flush=True)
                return -1
            ws = getattr(client, "_websocket", None)
            if ws is not None and connected_at is None:
                connected_at = time.time()
                print(f"   OK  握手成功，用时 {connected_at - t0:.1f}s", flush=True)
                stage(3, f"收弹幕 {seconds:.0f}s")
            if connected_at is not None:
                while len(got) > 0:
                    u, t = got.pop(0)
                    print(f"     <{u}> {t}", flush=True)
    finally:
        try:
            await client.stop_and_close()
        except Exception:
            pass
        if session is not None:
            try:
                await session.close()
            except Exception:
                pass

    if connected_at is None:
        print(f"   FAIL {seconds:.0f}s 内未建立连接", flush=True)
        return -1
    return len(got)


async def amain(args) -> int:
    print("=" * 68)
    print(f"B站弹幕接入自检  room={args.room_id}  观察 {args.seconds:.0f}s")
    print("=" * 68)

    jar, src = load_cookies(args)
    http_ok, codes, partial = await probe_http(args.room_id, jar)
    n = await probe_live(args.room_id, args.seconds, jar)

    print("\n" + "=" * 68)
    if not http_ok:
        if partial:
            print("有接口已通 => IP 没被封，差的是 cookie 的完整度。")
            print(f"  当前来源：{src}（{len(jar)} 个 cookie）")
            print("  用 ctest/cookie_export.js 导出真实浏览器的 cookie，覆盖")
            print("  ctest/bili_cookie.txt 后重跑；还不行再加 SESSDATA。")
            print("  成功时你会发现 blivedm 直连可用，就不必再常驻浏览器标签页了。")
            return 1
        elif not jar:
            print("匿名请求被风控。下一步：带上浏览器 cookie 再试一次 —— ")
            print("  ctest/cookie_export.js 导出 ->")
            print(f"  python ctest/blive_probe.py {args.room_id} "
                  "--cookie-file ctest/bili_cookie.txt")
            print("先只用 document.cookie 那部分；仍失败再加 SESSDATA。")
        else:
            print(f"带 cookie 仍被风控（来源 {src}）。")
            print("这个出口 IP 大概率是真被限了，别再折腾凭据 —— 改用")
            print("ctest/danmaku_userscript.js + --source http（读浏览器 DOM）。")
        print("结论：B站弹幕 API 对本机 IP 不可用 —— blivedm 直连路线走不通。")
        print("      用 ctest/danmaku_userscript.js + --source http（读浏览器 DOM）。")
        return 1
    if n < 0:
        print("结论：连不上。检查房间号是否正确、直播间是否真在开播。")
        return 1
    if n == 0:
        print("结论：链路完全通了，但这段时间没人说话 —— 属正常，不是故障。")
        print("      在自己直播间发一条弹幕再试一次来验证。")
        return 0
    print(f"结论：通了，收到 {n} 条。可以跑：")
    print(f"      .venv/Scripts/python.exe ctest/danmaku_bridge.py "
          f"--source bilibili --room-id {args.room_id}")
    print("=" * 68)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("room_id", type=int, help="直播间房间号（短号或长号均可）")
    p.add_argument("--seconds", type=float, default=30.0,
                   help="观察时长（秒）")
    p.add_argument("--cookie-file", default="",
                   help="文件：浏览器导出的 cookie（推荐，不进命令行历史）")
    p.add_argument("--cookie", default="",
                   help="或直接给 'k=v; k=v'（会进 shell history，尽量别用）")
    a = p.parse_args()
    try:
        sys.exit(asyncio.run(amain(a)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
