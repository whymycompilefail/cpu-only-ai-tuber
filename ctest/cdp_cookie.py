#!/usr/bin/env python3
"""
cdp_cookie.py -- read B站 login cookies out of a running Edge over CDP.

Why this exists
---------------
Edge stores cookies encrypted with AppBound Encryption (machine-scoped key).
We cannot decrypt that file ourselves, and we do not want to: a script that
cracks browser credential storage is indistinguishable from an infostealer,
and it would poison the open-source release.

CDP sidesteps all of it: we ask the *browser itself* to hand over the cookies
it has already decrypted for its own use. No crypto, no exploit, no
infostealer-shaped code.

Prerequisite: Edge must have been started with
    --remote-debugging-port=<port> --user-data-dir=<ascii path>
Chromium silently ignores --remote-debugging-port when the profile is at its
default (Chinese) path, which is why we copy Local State + Cookies to an
ASCII path first.

Usage
-----
    python ctest/cdp_cookie.py --probe          # report only, no secrets printed
    python ctest/cdp_cookie.py --export         # write ctest/bili_cookie.txt
"""

import argparse
import json
import os
import sys
import time
import urllib.request

try:
    import websocket
except ImportError:
    sys.exit("need the 'websocket-client' package (use Open-LLM-VTuber/.venv)")

PORT = int(os.environ.get("CDP_PORT", "9222"))
BASE = "http://127.0.0.1:%d" % PORT

WANTED = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5",
          "buvid3", "buvid4", "sid", "bili_ticket")


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as fh:
        return json.loads(fh.read().decode("utf-8"))


def new_target():
    """Open a blank tab we can attach to. Chrome requires PUT for /json/new."""
    try:
        return http_json(BASE + "/json/new?about:blank", method="PUT")
    except Exception:
        pass
    try:
        return http_json(BASE + "/json/new?about:blank", method="GET")
    except Exception as exc:
        sys.exit("cannot open a CDP target: %s\n"
                 "is Edge running with --remote-debugging-port=%d ?" % (exc, PORT))


def rpc(ws, mid, method, params=None):
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    deadline = time.time() + 15
    while time.time() < deadline:
        raw = ws.recv()
        if not raw:
            break
        obj = json.loads(raw)
        if obj.get("id") == mid:
            return obj
    return None


def fetch_cookies():
    tgt = new_target()
    ws = websocket.create_connection(tgt["webSocketDebuggerUrl"], timeout=20,
                                     suppress_origin=True)
    try:
        rpc(ws, 1, "Network.enable")
        res = rpc(ws, 2, "Network.getAllCookies")
        if not res or "result" not in res:
            sys.exit("Network.getAllCookies failed: %s" % (res,))
        return res["result"]["cookies"]
    finally:
        try:
            ws.close()
        except Exception:
            pass
        try:
            http_json(BASE + "/json/close/" + tgt["id"])
        except Exception:
            pass


def main():
    global PORT, BASE

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="report only")
    ap.add_argument("--export", action="store_true", help="write cookie file")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    PORT = args.port
    BASE = "http://127.0.0.1:%d" % PORT

    cookies = fetch_cookies()
    bili = [c for c in cookies if "bilibili" in c.get("domain", "")]

    print("total cookies visible : %d" % len(cookies))
    print("bilibili cookies      : %d" % len(bili))
    print()

    found = {}
    for c in bili:
        found[c["name"]] = c["value"]

    print("%-20s %-8s %s" % ("NAME", "LEN", "PRESENT"))
    for name in WANTED:
        val = found.get(name)
        print("%-20s %-8s %s" % (name, len(val) if val else 0,
                                 "yes" if val else "-- MISSING --"))

    if args.probe:
        if not found.get("SESSDATA"):
            print("\nSESSDATA absent => not logged in on this profile.")
            print("Log into bilibili in THIS Edge window, then re-run.")
        else:
            print("\nSESSDATA present => login state survived the copy.")
        return

    if args.export:
        if not found.get("SESSDATA"):
            sys.exit("refusing to write: no SESSDATA")
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "bili_cookie.txt")
        line = "; ".join("%s=%s" % (k, v) for k, v in sorted(found.items()))
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(line + "\n")
        os.chmod(out, 0o600)
        print("\nwrote %d cookies to %s" % (len(found), out))


if __name__ == "__main__":
    main()
