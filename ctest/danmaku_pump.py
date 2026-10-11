#!/usr/bin/env python3
"""danmaku_pump.py -- move danmaku from the live page to the bridge, over CDP.

    Open-LLM-VTuber/.venv/Scripts/python.exe ctest/danmaku_pump.py --room-id <id>

Why CDP and not a fetch() from the page
--------------------------------------
A page on https://live.bilibili.com cannot reach http://127.0.0.1:8765. This
was measured, not assumed:

  * the bridge answers the exact Local Network Access preflight Chrome sends
    (curl: 204 + Access-Control-Allow-Private-Network);
  * a no-preflight `text/plain` POST -- which cannot be blocked by CORS at all
    -- also never settles, so it is not a preflight problem;
  * neither --proxy-bypass-list nor --no-proxy-server changes it.

Public origin -> loopback is gated by Chrome and the request just hangs: no
response, no rejection, no console error. Debugging it from the page side is
hopeless because there is nothing to debug.

So the page is reduced to what it is uniquely able to do -- render the chat
that B站 already streams to it -- and this script, running as a normal local
process, does all the networking. It reads the page over the DevTools
WebSocket and POSTs to the bridge with a proxy-free opener.

The page keeps working while backgrounded (chat arrives over WebSocket and the
DOM mutates regardless of visibility), so the live-room tab does not have to
be the visible one -- which matters because 直播姬 captures the *other* tab,
the Live2D page on :12393.

Requires Edge started by ctest/edge_cdp.py (--remote-debugging-port=9222).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR = os.path.join(HERE, "danmaku_collector.js")

# Chrome considers the danmaku tab idle and freezes it, because the only thing
# ever touching it is our own Runtime.evaluate once a second -- no user input,
# no media, no animation. A frozen page stops running script without any error;
# the drain still answers, so the pump looks alive while catching nothing.
# Emulation.setPageScaleFactor forces the renderer to stay productive, and it
# changes nothing the user can see.
KEEPALIVE_SECS = 30

try:
    import websocket
except ImportError:
    sys.exit("need the 'websocket-client' package (use Open-LLM-VTuber/.venv)")

# A proxy-free opener: this box has a system proxy that does NOT bypass
# loopback, so a plain urlopen to :8765 returns 502.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(url, method="GET", timeout=10):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.loads(fh.read().decode("utf-8"))


class Cdp:
    """One page, one WebSocket, sequential request/response."""

    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=30,
                                              suppress_origin=True)
        self.mid = 0

    def call(self, method, params=None, timeout=30):
        self.mid += 1
        mid = self.mid
        msg = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            if not raw:
                break
            obj = json.loads(raw)
            if obj.get("id") == mid:
                return obj
        return None

    def evaluate(self, expr, timeout=30):
        res = self.call("Runtime.evaluate",
                        {"expression": expr, "returnByValue": True,
                         "awaitPromise": True}, timeout=timeout)
        if not res or "result" not in res:
            return None, "no result: %s" % (res,)
        r = res["result"]
        if r.get("exceptionDetails"):
            return None, json.dumps(r["exceptionDetails"],
                                    ensure_ascii=False)[:400]
        return r.get("result", {}).get("value"), None

    def navigate(self, url, timeout=60):
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url})
        for _ in range(timeout):
            time.sleep(1)
            v, err = self.evaluate("document.readyState")
            if v == "complete":
                return True
        return False

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def find_or_open(cdp_port: int, room_id: int, base: str) -> tuple[Cdp, str]:
    """Attach to the right tab: reuse the live room, else take a throwaway one.

    Order matters and this used to be wrong. It took pages[0] when no live-room
    tab existed -- and pages[0] is usually http://localhost:12393, the Live2D
    page holding the /inject handshake. Navigating away from it silently tore
    down `page=true`, i.e. the pump destroyed the very connection it needs to
    be useful, right after the runbook's step C established it.

    So: never hijack a tab that is doing work. Reuse an existing live-room tab,
    otherwise open a fresh one.

    Do not try to recycle a "blank" tab. /json/list reports the new tab as
    edge://newtab/, but its real location.href is https://ntp.msn.cn/edge/ntp,
    so the obvious blank-tab check matched the wrong page and the collector got
    installed onto the MSN start page -- which then reported chat pane
    {"kids":-1} forever. Always open instead; it costs one tab per stream.
    """
    targets = http_json("http://127.0.0.1:%d/json/list" % cdp_port)
    pages = [t for t in targets if t.get("type") == "page"]

    for t in pages:
        if "live.bilibili.com" in t.get("url", ""):
            print("[pump] reusing live tab: %s" % t["url"][:80], flush=True)
            return Cdp(t["webSocketDebuggerUrl"]), t["url"]

    url = "%s%d" % (base, room_id)
    t = http_json("http://127.0.0.1:%d/json/new?about:blank" % cdp_port,
                  method="PUT")
    c = Cdp(t["webSocketDebuggerUrl"])
    print("[pump] opened new tab for %s" % url, flush=True)
    c.navigate(url)
    return c, url


def install(c: Cdp) -> bool:
    with open(COLLECTOR, encoding="utf-8") as fh:
        src = fh.read()
    val, err = c.evaluate(src)
    if err:
        print("[pump] inject failed: %s" % err, flush=True)
        return False
    print("[pump] collector: %s" % val, flush=True)
    return True


def chat_health(c: Cdp) -> str:
    """Is the chat area actually rendering danmaku? An empty list means the
    tab is not logged in -- B站 does not load the chat pane for guests, which
    looks exactly like a dead collector."""
    expr = ("(function(){var l=document.querySelector('.chat-items');"
            "var n=l?l.children.length:-1;"
            "var p=/登录后可参与讨论/.test(document.body.innerText);"
            "return JSON.stringify({kids:n,login_wall:p});})()")
    val, err = c.evaluate(expr)
    return val if val else ("err: %s" % err)


def post(items, bridge: str) -> int:
    if not items:
        return 0
    data = json.dumps(items).encode("utf-8")
    req = urllib.request.Request(bridge, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=10) as fh:
        fh.read()
    return len(items)


def run_session(args) -> None:
    """One attach-and-pump cycle. Raises if the tab or the browser goes away.

    Kept separate from main() so that losing the socket is a reconnect, not a
    crash: the first version propagated a `ConnectionAbortedError` out of the
    poll loop and died 28 minutes into a session. A stream is longer than one
    WebSocket's lifetime, so the death of a connection must never be fatal.
    """
    c, _url = find_or_open(args.cdp_port, args.room_id, args.base)
    try:
        time.sleep(2)
        print("[pump] chat pane: %s" % chat_health(c), flush=True)
        if not install(c):
            return

        missed = 0
        forwarded = 0
        last_tick = time.time()
        last_keepalive = time.time()
        print("[pump] pumping every %.1fs -- Ctrl-C to stop" % args.interval,
              flush=True)
        while True:
            time.sleep(args.interval)
            # This tab answers CDP polls all day, so Chrome sees it as idle and
            # freezes it: script evaluation stops dead. 15 minutes of catching
            # nothing while the control link stays up is exactly that. Keeping
            # it awake is cheaper than debugging it again.
            if time.time() - last_keepalive >= KEEPALIVE_SECS:
                c.call("Emulation.setPageScaleFactor", {"pageScaleFactor": 1},
                       timeout=15)
                last_keepalive = time.time()

            val, _err = c.evaluate(
                "window.__danmakuCollector__ ?"
                " JSON.stringify(window.__danmakuCollector__.drain())"
                " : null")

            # Heartbeat: without it an idle room and a hung pump read the same
            # from the outside -- clean logs and nothing happening.
            if args.heartbeat and time.time() - last_tick >= args.heartbeat:
                print("[pump] alive -- %d forwarded so far" % forwarded,
                      flush=True)
                last_tick = time.time()

            if val is None:
                # Page navigated or the tab was recreated: reinstall.
                missed += 1
                if missed >= 3:
                    print("[pump] collector gone (page reloaded?) "
                          "-- reinstalling", flush=True)
                    install(c)
                    missed = 0
                continue
            missed = 0
            items = json.loads(val) if val else []
            if not items:
                continue
            post(items, args.bridge)
            forwarded += len(items)
            for it in items:
                print("[pump] <%s> %s" % (it.get("user"), it.get("text")),
                      flush=True)
    finally:
        c.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--room-id", type=int, default=0)
    ap.add_argument("--cdp-port", type=int, default=9222)
    ap.add_argument("--bridge", default="http://127.0.0.1:8765/danmaku")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--heartbeat", type=float, default=60.0,
                    help="seconds between liveness lines (0 disables)")
    ap.add_argument("--base", default="https://live.bilibili.com/")
    ap.add_argument("--once", action="store_true",
                    help="drain one batch and exit (diagnostic)")
    args = ap.parse_args()

    if args.once:
        c, _ = find_or_open(args.cdp_port, args.room_id, args.base)
        try:
            time.sleep(2)
            c.evaluate(open(COLLECTOR, encoding="utf-8").read())
            val, err = c.evaluate(
                "JSON.stringify(window.__danmakuCollector__.stats())")
            print("[pump] stats: %s %s" % (val, err or ""), flush=True)
            val, _ = c.evaluate(
                "JSON.stringify(window.__danmakuCollector__.drain())")
            items = json.loads(val) if val else []
            print("[pump] drained %d: %s" % (len(items), items[:5]), flush=True)
            print("[pump] posted %d" % post(items, args.bridge), flush=True)
        finally:
            c.close()
        return 0

    backoff = 3.0
    while True:
        try:
            run_session(args)
            backoff = 3.0            # clean return => reset
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print("[pump] session ended (%s: %s) -- retrying in %.0fs"
                  % (type(e).__name__, e, backoff), flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    sys.exit(main())
