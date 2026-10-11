#!/usr/bin/env python3
"""
cdp_focus.py -- bring the CDP-controlled Edge window to the foreground.

    python ctest/cdp_focus.py info     window state as the browser reports it
    python ctest/cdp_focus.py bring    restore + activate + front

A detached/background-launched Edge can end up minimized or behind other
windows; Browser.setWindowBounds + Page.bringToFront is what actually surfaces
it.
"""

import json
import sys
import urllib.request

try:
    import websocket
except ImportError:
    sys.exit("need 'websocket-client' (use Open-LLM-VTuber/.venv)")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9222
MODE = sys.argv[1] if len(sys.argv) > 1 else "info"
BASE = "http://127.0.0.1:%d" % PORT


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=15) as fh:
        return json.loads(fh.read().decode("utf-8"))


def room_target():
    for t in http_json(BASE + "/json/list"):
        if t.get("type") == "page" and "live.bilibili.com" in t.get("url", ""):
            return t
    return None


class Browser(object):
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=30,
                                              suppress_origin=True)
        self.mid = 0

    def call(self, method, params=None):
        self.mid += 1
        mid = self.mid
        msg = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        deadline = 20
        while deadline > 0:
            deadline -= 1
            obj = json.loads(self.ws.recv())
            if obj.get("id") == mid:
                return obj
        return None

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def main():
    tgt = room_target()
    if not tgt:
        sys.exit("no live.bilibili.com tab open")

    ver = http_json(BASE + "/json/version")
    br = Browser(ver["webSocketDebuggerUrl"])
    try:
        win = br.call("Browser.getWindowForTarget", {"targetId": tgt["id"]})
        if not win or "result" not in win:
            sys.exit("cannot query window: %s" % (win,))
        res = win["result"]
        print("windowId    : %s" % res.get("windowId"))
        print("bounds      : %s" % json.dumps(res.get("bounds"),
                                              ensure_ascii=False))

        if MODE == "bring":
            wid = res["windowId"]
            r1 = br.call("Browser.setWindowBounds", {
                "windowId": wid,
                "bounds": {"windowState": "normal",
                           "left": 80, "top": 60,
                           "width": 1440, "height": 900}})
            print("setWindowBounds: %s" % ("ok" if r1 and "result" in r1
                                           else r1))
            r2 = br.call("Target.activateTarget", {"targetId": tgt["id"]})
            print("activateTarget : %s" % ("ok" if r2 and "result" in r2
                                           else r2))
            pg = Browser(tgt["webSocketDebuggerUrl"])
            try:
                r3 = pg.call("Page.bringToFront")
                print("bringToFront   : %s" % ("ok" if r3 and "result" in r3
                                               else r3))
            finally:
                pg.close()
            print("\nwindow should now be visible: %s" % tgt.get("title"))
    finally:
        br.close()


if __name__ == "__main__":
    main()
