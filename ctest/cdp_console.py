#!/usr/bin/env python3
"""
cdp_console.py -- listen to what a page prints, and whether the inject ran.

    python ctest/cdp_console.py <url-fragment> [seconds]

Answers the question that cannot be answered from the outside: did
danmaku_inject.js actually execute, and did its WebSocket back to the bridge
open or fail? Both failure modes look identical from /stats (page=false).
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

FRAG = sys.argv[1] if len(sys.argv) > 1 else "12393"
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
PORT = 9222
BASE = "http://127.0.0.1:%d" % PORT

PROBE_JS = """
(function () {
  var src = String(window.WebSocket);
  return {
    ready: document.readyState,
    inject_present: !!(window.WebSocket && src.indexOf('native code') < 0),
    ws_src_head: src.slice(0, 90),
    scripts: Array.prototype.slice.call(
      document.querySelectorAll('script[src]')).map(function (s) {
        return s.getAttribute('src');
      }).slice(0, 8)
  };
})()
"""


def main():
    tgt = None
    for t in json.loads(urllib.request.urlopen(BASE + "/json/list",
                                               timeout=15).read()):
        if t.get("type") == "page" and FRAG in t.get("url", ""):
            tgt = t
            break
    if not tgt:
        sys.exit("no tab matching %r" % FRAG)

    print("tab   : %s" % tgt.get("url"))
    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=40,
                                     suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Log.enable"}))
    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate",
                        "params": {"expression": PROBE_JS,
                                   "returnByValue": True}}))

    msgs = []
    probe = None
    end = time.time() + SECS
    ws.settimeout(1)
    while time.time() < end:
        try:
            obj = json.loads(ws.recv())
        except Exception:
            continue
        if obj.get("id") == 3:
            probe = obj.get("result", {}).get("result", {}).get("value")
            continue
        m = obj.get("method")
        if m in ("Runtime.consoleAPICalled", "Log.entryAdded"):
            p = obj.get("params", {})
            if m == "Runtime.consoleAPICalled":
                text = " ".join(str(a.get("value")) for a in p.get("args", []))
                msgs.append("[%s] %s" % (p.get("type"), text))
            else:
                e = p.get("entry", {})
                msgs.append("[log:%s] %s" % (e.get("level"), e.get("text")))

    print("ready : %s" % (probe or {}).get("ready"))
    print("inject patched WebSocket: %s" % (probe or {}).get("inject_present"))
    print("WebSocket src: %s" % (probe or {}).get("ws_src_head"))
    print("scripts: %s" % (probe or {}).get("scripts"))
    print()
    print("--- console (%ds) ---" % SECS)
    if not msgs:
        print("(silent -- no console output at all)")
    for line in msgs[:40]:
        print(line)
    ws.close()


if __name__ == "__main__":
    main()
