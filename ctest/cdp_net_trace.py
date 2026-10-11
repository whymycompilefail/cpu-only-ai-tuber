#!/usr/bin/env python3
"""
cdp_net_trace.py -- fire a POST at the bridge and report what Chrome says.

    python ctest/cdp_net_trace.py <url-fragment> [seconds]

Chrome labels blocked requests with a reason (mixed-content, cors,
private-network, ...). Reading that reason beats guessing, especially when the
fetch Promise never settles and therefore reports nothing at all.
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

FRAG = sys.argv[1] if len(sys.argv) > 1 else "live.bilibili.com"
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 14
PORT = 9222
BASE = "http://127.0.0.1:%d" % PORT

FIRE_JS = """
(function () {
  try {
    fetch('http://127.0.0.1:8765/danmaku', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user: 'nettrace', text: 'trace probe'})
    }).then(function (r) { console.log('TRACE ok ' + r.status); })
      .catch(function (e) { console.log('TRACE fail ' + e); });
  } catch (e) { console.log('TRACE threw ' + e); }
  return 'fired';
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

    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=45,
                                     suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Runtime.enable"}))
    time.sleep(1)
    ws.send(json.dumps({"id": 3, "method": "Runtime.evaluate",
                        "params": {"expression": FIRE_JS,
                                   "returnByValue": True}}))

    end = time.time() + SECS
    ws.settimeout(1)
    t0 = time.time()
    out = []
    while time.time() < end:
        try:
            obj = json.loads(ws.recv())
        except Exception:
            continue
        m = obj.get("method", "")
        p = obj.get("params", {})
        if m == "Network.requestWillBeSent":
            r = p.get("request", {})
            out.append("+%.1fs REQUEST %s %s"
                       % (time.time() - t0, r.get("method"),
                          r.get("url", "")[:60]))
        elif m == "Network.responseReceived":
            r = p.get("response", {})
            out.append("+%.1fs RESPONSE status=%s %s"
                       % (time.time() - t0, r.get("status"),
                          r.get("url", "")[:52]))
        elif m == "Network.loadingFailed":
            out.append("+%.1fs FAILED blockedReason=%s errorText=%s %s"
                       % (time.time() - t0, p.get("blockedReason"),
                          p.get("errorText"), p.get("type")))
        elif m == "Network.loadingFinished":
            out.append("+%.1fs FINISHED" % (time.time() - t0))
        elif m == "Runtime.consoleAPICalled":
            txt = " ".join(str(a.get("value")) for a in p.get("args", []))
            if "TRACE" in txt:
                out.append("+%.1fs %s" % (time.time() - t0, txt))

    print("--- network trace on %s ---" % tgt.get("url"))
    if not out:
        print("  (nothing observed)")
    for ln in out[:30]:
        print("  %s" % ln)
    ws.close()


if __name__ == "__main__":
    main()
