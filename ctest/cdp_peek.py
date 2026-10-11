#!/usr/bin/env python3
"""cdp_peek.py -- is the danmaku area merely empty, or is it login-gated?"""

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
BASE = "http://127.0.0.1:%d" % PORT

JS = """
(function () {
  function txt(sel) {
    var e = document.querySelector(sel);
    return e ? (e.textContent || '').trim() : null;
  }
  function kids(sel) {
    var e = document.querySelector(sel);
    return e ? e.children.length : -1;
  }
  var body = document.body.innerText || '';
  return {
    chat_items_kids: kids('.chat-items'),
    chat_items_text: (txt('.chat-items') || '').slice(0, 300),
    history_list_kids: kids('.chat-history-list'),
    panel_text: (txt('.chat-history-panel') || '').slice(0, 200),
    control_text: (txt('.chat-control-panel') || '').slice(0, 120),
    body_has_login_prompt: /登录后可参与讨论|请先登录/.test(body),
    body_len: body.length,
    url: location.href,
    has_login_btn: !!document.querySelector('.chat-history-panel a, .chat-history-panel .login, [class*=login]')
  };
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
        deadline = time.time() + 30
        while time.time() < deadline:
            obj = json.loads(ws.recv())
            if obj.get("id") == 1:
                r = obj.get("result", {}).get("result", {}).get("value")
                for k, v in (r or {}).items():
                    print("%-24s %s" % (k, v))
                return
    finally:
        ws.close()


if __name__ == "__main__":
    main()
