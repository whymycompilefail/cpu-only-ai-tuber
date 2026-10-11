#!/usr/bin/env python3
"""
cdp_danmaku_probe.py -- read the REAL danmaku DOM out of a live bilibili room.

The earlier userscript failed because its SELECTORS were guessed from generic
bilibili class names. Guessing wrong is silent: zero matches, no error, the
bridge just never sees anything. This script stops guessing -- it attaches to
the actual page and reports what the page actually contains.

Phase A  static scan: which classes exist, how many, sample text
Phase B  MutationObserver: catch nodes the page ADDS while we watch, and
         report the exact selector path of each -- this is what a real danmaku
         node looks like right now, on this machine, in this browser build.
"""

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

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9222
WATCH = int(sys.argv[2]) if len(sys.argv) > 2 else 20
BASE = "http://127.0.0.1:%d" % PORT


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=15) as fh:
        return json.loads(fh.read().decode("utf-8"))


def find_room_target():
    for t in http_json(BASE + "/json/list"):
        if t.get("type") == "page" and "live.bilibili.com" in t.get("url", ""):
            return t
    return None


def attach(tgt):
    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=30,
                                     suppress_origin=True)
    return ws


def evaluate(ws, expr, mid=1):
    ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                        "params": {"expression": expr,
                                   "returnByValue": True,
                                   "awaitPromise": False}}))
    deadline = time.time() + 30
    while time.time() < deadline:
        obj = json.loads(ws.recv())
        if obj.get("id") == mid:
            return obj.get("result", {}).get("result", {}).get("value")
    return None


SCAN_JS = """
(function () {
  var hits = {};
  var all = document.querySelectorAll('*');
  for (var i = 0; i < all.length; i++) {
    var e = all[i];
    var cls = (typeof e.className === 'string') ? e.className : '';
    if (!cls) continue;
    var parts = cls.split(/\\s+/);
    for (var j = 0; j < parts.length; j++) {
      var c = parts[j];
      if (!c) continue;
      if (/danmaku|chat|message|msg|comment/i.test(c)) {
        if (!hits[c]) hits[c] = {n: 0, sample: ''};
        hits[c].n++;
        if (!hits[c].sample && e.textContent) {
          hits[c].sample = e.textContent.trim().slice(0, 40);
        }
      }
    }
  }
  var out = [];
  for (var k in hits) out.push({cls: k, n: hits[k].n, sample: hits[k].sample});
  out.sort(function (a, b) { return b.n - a.n; });
  return out.slice(0, 25);
})()
"""

START_JS = """
(function () {
  window.__dm = {items: [], count: 0};
  function path(el) {
    var p = [];
    while (el && el.nodeType === 1 && p.length < 6) {
      var cls = (typeof el.className === 'string' && el.className)
        ? el.className.trim().split(/\\s+/)[0] : '';
      p.unshift(el.tagName.toLowerCase() + (cls ? '.' + cls : ''));
      el = el.parentElement;
    }
    return p.join(' > ');
  }
  var obs = new MutationObserver(function (muts) {
    for (var m of muts) {
      for (var n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        window.__dm.count++;
        if (window.__dm.items.length < 40) {
          window.__dm.items.push({
            tag: n.tagName.toLowerCase(),
            cls: (typeof n.className === 'string') ? n.className : '',
            path: path(n),
            text: (n.textContent || '').trim().slice(0, 60)
          });
        }
      }
    }
  });
  obs.observe(document.body, {childList: true, subtree: true});
  return 'observing';
})()
"""

READ_JS = "(function(){ return window.__dm; })()"


def main():
    tgt = find_room_target()
    if not tgt:
        sys.exit("no live.bilibili.com tab open")
    print("page : %s" % tgt.get("title"))
    print("url  : %s" % tgt.get("url"))
    print()

    ws = attach(tgt)
    try:
        print("--- A. static scan: classes in the page right now ---")
        scan = evaluate(ws, SCAN_JS, 1) or []
        print("%-42s %6s  %s" % ("CLASS", "COUNT", "SAMPLE TEXT"))
        for row in scan:
            print("%-42s %6d  %s" % (row["cls"][:42], row["n"],
                                     row["sample"][:34]))
        print()
        print("--- B. watching %ds for nodes the page adds ---" % WATCH)
        print(evaluate(ws, START_JS, 2))
        time.sleep(WATCH)
        dm = evaluate(ws, READ_JS, 3) or {}
        print("nodes added while watching: %s" % dm.get("count", 0))
        print()
        print("%-30s %s" % ("SELECTOR PATH", "TEXT"))
        for it in (dm.get("items") or [])[:20]:
            print("%-30s %s" % (it["path"][:30], it["text"][:44]))
    finally:
        ws.close()


if __name__ == "__main__":
    main()
