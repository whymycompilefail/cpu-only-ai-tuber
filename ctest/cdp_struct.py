#!/usr/bin/env python3
"""
cdp_struct.py -- dump ONE real danmaku node so the collector can be written
against facts instead of guesses.

The old userscript hardcoded user="viewer" precisely because nobody had ever
looked at how a bilibili chat row separates the sender name from the message
text. This prints that structure.
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

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9222
BASE = "http://127.0.0.1:%d" % PORT

JS = """
(function () {
  function dump(sel) {
    var items = document.querySelectorAll(sel);
    if (!items.length) return null;
    var e = items[items.length - 1];
    var kids = [];
    var all = e.querySelectorAll('*');
    for (var i = 0; i < all.length && i < 30; i++) {
      var k = all[i];
      kids.push({
        tag: k.tagName.toLowerCase(),
        cls: String(k.className || '').slice(0, 46),
        text: (k.textContent || '').trim().slice(0, 40)
      });
    }
    return {
      selector: sel,
      count: items.length,
      outer: e.outerHTML.slice(0, 900),
      kids: kids
    };
  }
  var cands = ['.chat-items > *', '.chat-item', '.danmaku-item',
               '.chat-history-list > *'];
  for (var i = 0; i < cands.length; i++) {
    var d = dump(cands[i]);
    if (d) return d;
  }
  return {error: 'no danmaku node found', tried: cands};
})()
"""


def main():
    tgt = None
    for t in json.loads(urllib.request.urlopen(BASE + "/json/list",
                                               timeout=15).read()):
        if t.get("type") == "page" and "live.bilibili.com" in t.get("url", ""):
            tgt = t
            break
    if not tgt:
        sys.exit("no live.bilibili.com tab")

    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=30,
                                     suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": JS,
                                       "returnByValue": True}}))
        end = 30
        while end > 0:
            end -= 1
            obj = json.loads(ws.recv())
            if obj.get("id") == 1:
                r = obj.get("result", {}).get("result", {}).get("value") or {}
                if r.get("error"):
                    print("ERROR: %s" % r)
                    return
                print("selector : %s" % r.get("selector"))
                print("count    : %s" % r.get("count"))
                print()
                print("--- outerHTML (trimmed) ---")
                print(r.get("outer", ""))
                print()
                print("--- children ---")
                print("%-6s %-46s %s" % ("TAG", "CLASS", "TEXT"))
                for k in r.get("kids", []):
                    print("%-6s %-46s %s" % (k["tag"], k["cls"], k["text"]))
                return
    finally:
        ws.close()


if __name__ == "__main__":
    main()
