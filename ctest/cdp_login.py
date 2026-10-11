#!/usr/bin/env python3
"""
cdp_login.py -- drive the bilibili login popup over CDP and grab the QR code.

    python ctest/cdp_login.py shot [out.png]   click login, wait, screenshot
    python ctest/cdp_login.py wait [seconds]   poll until SESSDATA appears

The QR code lives inside the page the browser already has, so we never touch
credential storage: we just ask the page to show it and take a picture.
"""

import base64
import json
import sys
import time
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
BASE = "http://127.0.0.1:%d" % PORT
MODE = sys.argv[1] if len(sys.argv) > 1 else "shot"


def targets():
    return json.loads(urllib.request.urlopen(BASE + "/json/list",
                                             timeout=15).read())


def room_target():
    for t in targets():
        if t.get("type") == "page" and "live.bilibili.com" in t.get("url", ""):
            return t
    return None


class Page(object):
    def __init__(self, tgt):
        self.ws = websocket.create_connection(tgt["webSocketDebuggerUrl"],
                                              timeout=30, suppress_origin=True)
        self.mid = 0

    def call(self, method, params=None, timeout=40):
        self.mid += 1
        mid = self.mid
        msg = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while time.time() < deadline:
            obj = json.loads(self.ws.recv())
            if obj.get("id") == mid:
                return obj
        return None

    def js(self, expr):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True})
        if not r:
            return None
        return r.get("result", {}).get("result", {}).get("value")

    def shot(self, path):
        r = self.call("Page.captureScreenshot", {"format": "png"})
        if not r or "result" not in r:
            return None
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(r["result"]["data"]))
        return path

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


FIND_JS = """
(function () {
  var out = [];
  var els = document.querySelectorAll('a,button,span,div,li');
  for (var i = 0; i < els.length; i++) {
    var e = els[i];
    var t = (e.textContent || '').trim();
    if (t === '登录' || t === '立即登录' || t === '登录后可参与讨论 登录') {
      var r = e.getBoundingClientRect();
      out.push({tag: e.tagName, cls: String(e.className).slice(0,40),
                text: t.slice(0, 24), w: Math.round(r.width),
                h: Math.round(r.height), top: Math.round(r.top)});
    }
  }
  return out;
})()
"""

CLICK_JS = """
(function () {
  var els = document.querySelectorAll('a,button,span,div,li');
  for (var i = 0; i < els.length; i++) {
    var e = els[i];
    var t = (e.textContent || '').trim();
    if (t === '登录' || t === '立即登录') {
      var r = e.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        e.click();
        return 'clicked ' + e.tagName + '.' + String(e.className).slice(0,30);
      }
    }
  }
  return 'no visible login element';
})()
"""

COOKIE_JS = "(function(){ return document.cookie.indexOf('SESSDATA') >= 0; })()"


def main():
    tgt = room_target()
    if not tgt:
        sys.exit("no live.bilibili.com tab open (port %d)" % PORT)

    pg = Page(tgt)
    try:
        if MODE == "shot":
            out = sys.argv[3] if len(sys.argv) > 3 else "ctest/login_qr.png"
            print("candidates: %s" % json.dumps(pg.js(FIND_JS),
                                                ensure_ascii=False))
            print(pg.js(CLICK_JS))
            time.sleep(5)
            p = pg.shot(out)
            print("screenshot: %s" % p if p else "screenshot FAILED")
            print("SESSDATA now: %s" % pg.js(COOKIE_JS))

        elif MODE == "wait":
            secs = int(sys.argv[3]) if len(sys.argv) > 3 else 180
            print("polling up to %ds for SESSDATA ..." % secs)
            for i in range(secs // 5):
                time.sleep(5)
                if pg.js(COOKIE_JS):
                    print("LOGGED IN after ~%ds" % ((i + 1) * 5))
                    return
            print("still not logged in")
    finally:
        pg.close()


if __name__ == "__main__":
    main()
