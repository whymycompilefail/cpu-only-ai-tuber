#!/usr/bin/env python3
"""
cdp_ws_trace.py -- watch the browser's own network layer for WebSocket events.

    python ctest/cdp_ws_trace.py <url> [seconds]

Console logging can lie (throttled timers, missed attach windows). The network
stack cannot: if a ws:// handshake was attempted, attempted-and-failed, or
never attempted at all, these events say which.
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
WS_EVENTS = ("Network.webSocketCreated",
             "Network.webSocketHandshakeResponseReceived",
             "Network.webSocketClosed",
             "Network.webSocketWillSendHandshakeRequest",
             "Network.webSocketFrameError",
             "Network.loadingFailed")


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=20) as fh:
        return json.loads(fh.read().decode("utf-8"))


def main():
    tgt = http_json(BASE + "/json/new?about:blank", method="PUT")
    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=45,
                                     suppress_origin=True)
    ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
    ws.send(json.dumps({"id": 2, "method": "Page.enable"}))
    ws.send(json.dumps({"id": 3, "method": "Runtime.enable"}))
    time.sleep(1)
    print("navigating to %s" % URL)
    ws.send(json.dumps({"id": 4, "method": "Page.navigate",
                        "params": {"url": URL}}))

    end = time.time() + SECS
    ws.settimeout(1)
    lines = []
    t0 = time.time()
    while time.time() < end:
        try:
            obj = json.loads(ws.recv())
        except Exception:
            continue
        m = obj.get("method")
        if m in WS_EVENTS:
            p = obj.get("params", {})
            url = p.get("url", "")
            if "8765" in url or "inject" in url or m.startswith("Network.webSocket"):
                detail = ""
                if m == "Network.webSocketHandshakeResponseReceived":
                    r = p.get("response", {})
                    detail = "status=%s" % r.get("status")
                elif m == "Network.webSocketClosed":
                    detail = "closed"
                elif m == "Network.loadingFailed":
                    detail = "failed: %s" % p.get("errorText")
                lines.append("+%.1fs %-52s %s %s"
                             % (time.time() - t0, m.replace("Network.", ""),
                                url[:46], detail))
        elif m == "Runtime.consoleAPICalled":
            txt = " ".join(str(a.get("value"))
                           for a in obj.get("params", {}).get("args", []))
            if "danmaku-inject" in txt:
                lines.append("+%.1fs console: %s" % (time.time() - t0, txt))

    print()
    print("--- websocket / console trace (%ds) ---" % SECS)
    if not lines:
        print("  (no websocket events at all)")
    for ln in lines[:40]:
        print("  %s" % ln)
    ws.close()


if __name__ == "__main__":
    main()
