#!/usr/bin/env python3
"""
cdp_eval.py -- run a JS file inside a page and print its value.

    python ctest/cdp_eval.py <url-fragment> <js-file> [--await]

JS comes from a file so shell quoting never mangles it.
Use --await when the expression returns a Promise (fetch, timers).
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

FRAG = sys.argv[1]
JSFILE = sys.argv[2]
AWAIT = "--await" in sys.argv
PORT = 9222
BASE = "http://127.0.0.1:%d" % PORT


def main():
    with open(JSFILE, "r", encoding="utf-8") as fh:
        expr = fh.read()

    tgt = None
    for t in json.loads(urllib.request.urlopen(BASE + "/json/list",
                                               timeout=15).read()):
        if t.get("type") == "page" and FRAG in t.get("url", ""):
            tgt = t
            break
    if not tgt:
        sys.exit("no tab matching %r" % FRAG)

    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=40,
                                     suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expr,
                                       "returnByValue": True,
                                       "awaitPromise": AWAIT}}))
        end = time.time() + 40
        while time.time() < end:
            obj = json.loads(ws.recv())
            if obj.get("id") == 1:
                res = obj.get("result", {})
                if "exceptionDetails" in res:
                    print("EXCEPTION: %s" % json.dumps(
                        res["exceptionDetails"], ensure_ascii=False)[:400])
                    return
                print(res.get("result", {}).get("value"))
                return
    finally:
        ws.close()


if __name__ == "__main__":
    main()
