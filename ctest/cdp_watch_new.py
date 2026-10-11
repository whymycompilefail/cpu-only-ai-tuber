#!/usr/bin/env python3
"""
cdp_watch_new.py -- open a fresh tab and watch its console from second zero.

    python ctest/cdp_watch_new.py <url> [seconds]

The whole point is timing: on a tab opened earlier, the inject handshake has
already happened (or already failed) before we can attach, so its log line is
missed and we cannot tell success from silence. Opening the tab ourselves and
attaching before it loads removes that blind spot.
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

URL = sys.argv[1]
SECS = int(sys.argv[2]) if len(sys.argv) > 2 else 18
PORT = 9222
BASE = "http://127.0.0.1:%d" % PORT


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=20) as fh:
        return json.loads(fh.read().decode("utf-8"))


def stats():
    try:
        req = urllib.request.Request("http://127.0.0.1:8765/stats")
        req.add_header("no-proxy", "")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=8) as fh:
            return json.loads(fh.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def main():
    # Open blank FIRST, attach, THEN navigate. Creating the tab with ?url= makes
    # the page start loading before we can attach, so (a) the earliest console
    # lines are missed and (b) cache disabling arrives too late -- we end up
    # verifying an old cached danmaku_inject.js and chasing a phantom.
    tgt = http_json(BASE + "/json/new?about:blank", method="PUT")
    print("opened blank, navigating to %s" % URL)
    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=45,
                                     suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Log.enable"}))
    ws.send(json.dumps({"id": 3, "method": "Network.enable"}))
    ws.send(json.dumps({"id": 4, "method": "Network.setCacheDisabled",
                        "params": {"cacheDisabled": True}}))
    ws.send(json.dumps({"id": 5, "method": "Page.enable"}))
    time.sleep(1)
    ws.send(json.dumps({"id": 6, "method": "Page.navigate",
                        "params": {"url": URL}}))

    hits = []
    end = time.time() + SECS
    ws.settimeout(1)
    while time.time() < end:
        try:
            obj = json.loads(ws.recv())
        except Exception:
            continue
        m = obj.get("method")
        if m == "Runtime.consoleAPICalled":
            p = obj.get("params", {})
            text = " ".join(str(a.get("value")) for a in p.get("args", []))
            if "danmaku-inject" in text or "bridge" in text.lower():
                hits.append(text)
        elif m == "Log.entryAdded":
            e = obj.get("params", {}).get("entry", {})
            t = e.get("text", "")
            if "danmaku-inject" in t:
                hits.append(t)

    print()
    print("--- inject-related console lines (%ds) ---" % SECS)
    if hits:
        for h in hits[:15]:
            print("  %s" % h)
    else:
        print("  (none -- the handshake never logged anything)")

    print()
    print("bridge /stats after load:")
    print("  %s" % json.dumps(stats(), ensure_ascii=False))
    ws.close()


if __name__ == "__main__":
    main()
