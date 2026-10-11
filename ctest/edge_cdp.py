#!/usr/bin/env python3
"""
edge_cdp.py -- start Edge with the DevTools port open, for the rig to drive.

Three traps this script exists to avoid
---------------------------------------
1. Chromium refuses to open --remote-debugging-port on the DEFAULT profile.

   Measured, all four combinations tried: with the default profile the port
   never comes up, and it STILL does not when you pass
   --user-data-dir=<the default path> explicitly. Chromium keys the refusal
   off the path's *value*, not off whether the switch was given. So this rig
   uses a throwaway profile with an ASCII path:

       python ctest/edge_cdp.py --profile C:/temp/vtuber-edge --wait

   First run is bare: scan the QR code to log into bilibili (see below for why
   login is mandatory). The profile is reused afterwards and keeps the session.

2. Passing a Chinese path through Git Bash mangles the bytes, so Edge never
   sees --user-data-dir and therefore drops the debug port. Launching from
   Python (CreateProcessW) keeps the path intact.

3. Everything here has to stay resident, and it does not survive on its own.
   DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP was tried and did NOT keep the
   browser alive; nor did `&`, `disown`, or nohup. The only thing that works in
   this environment is launching the script as a background task and passing
   --wait so the launcher never exits. See LIVE_RUNBOOK.md.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9222


def default_profile():
    return os.path.join(os.path.expanduser("~"),
                        "AppData", "Local", "Microsoft", "Edge", "User Data")


def kill_edge():
    subprocess.run(["taskkill", "/IM", "msedge.exe", "/F"],
                   capture_output=True)
    for _ in range(15):
        time.sleep(1)
        # tasklist prints GBK Chinese on zh-CN Windows; decoding it as UTF-8
        # raises and yields None. Compare raw bytes instead.
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq msedge.exe"],
                             capture_output=True).stdout
        if b"msedge.exe" not in (out or b""):
            return True
    return False


def wait_port(port, seconds=40):
    url = "http://127.0.0.1:%d/json/version" % port
    for _ in range(seconds):
        time.sleep(1)
        try:
            with urllib.request.urlopen(url, timeout=3) as fh:
                return json.loads(fh.read().decode("utf-8"))
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--profile", default=default_profile())
    ap.add_argument("--wait", action="store_true",
                    help="stay alive so the browser is not reaped")
    args = ap.parse_args()

    print("profile: %s" % args.profile)
    print("exists : %s" % os.path.isdir(args.profile))

    print("killing existing Edge ...")
    print("  cleaned" if kill_edge() else "  WARNING: some processes remain")

    # Deliberately plain: no --no-proxy-server, no --disable-web-security.
    #
    # Those were added while trying to make a bilibili page fetch() straight to
    # http://127.0.0.1:8765. It never worked and they never helped -- the
    # request from a public https origin to loopback is gated by Chrome's Local
    # Network Access and simply hangs (no response, no rejection). The fix was
    # architectural: ctest/danmaku_collector.js no longer does any networking,
    # and ctest/danmaku_pump.py moves the danmaku over CDP from Python instead.
    # Since nothing in the page talks to loopback any more, a stock browser is
    # both sufficient and what we want to ship.
    #
    # The anti-throttling switches below are the exception, and they are not a
    # security relaxation. Measured failure: danmaku_inject.js retries its
    # bridge socket with a 2s setTimeout, but the Live2D tab is usually NOT the
    # focused one (only one tab can be visible, and the visible tab is the one
    # being captured). A hidden tab's timers get throttled to roughly one per
    # minute, so a dropped socket stayed down 79 seconds -- the AI went silent
    # mid-stream with no error anywhere. None of these relax any security
    # boundary; they only say "do not slow down my background tabs", which is
    # what a kiosk/automation browser wants by definition.
    cmd = [EDGE,
           "--remote-debugging-port=%d" % args.port,
           "--user-data-dir=%s" % args.profile,
           "--disable-background-timer-throttling",
           "--disable-backgrounding-occluded-windows",
           "--disable-renderer-backgrounding",
           # Chromium takes exactly ONE --disable-features. A second occurrence
           # silently drops the first, which is how the CalculateNativeWinOcclusion
           # half got lost on the first attempt later on: a duplicate
           # --disable-features=msEdgeSleepingTabs had quietly overridden it.
           # Everything belongs in the single comma-separated list below, and
           # there is deliberately no second list in this command.
           #   CalculateNativeWinOcclusion  off  (window deemed hidden -> freeze)
           #   msEdgeSleepingTabs           off  (Edge sleeps idle tabs)
           # Do not extend this list without measuring; the entries above are
           # ones we have actually seen cost audio.
           "--disable-features=CalculateNativeWinOcclusion,msEdgeSleepingTabs",
           # An invisible tab never receives "user activation", so Chrome refuses
           # to play 米粒's audio element: the round runs, her mouth moves, and
           # nothing reaches the speakers and nothing is logged. Necessary but
           # not sufficient -- the tab also has to be awake, hence the switches
           # above. Both halves are required or you get silence either way.
           "--autoplay-policy=no-user-gesture-required",
           "--no-first-run",
           "--no-default-browser-check"]
    print("launching Edge on port %d ..." % args.port)
    # NOTE: these flags do NOT keep the browser alive by themselves -- leaving
    # them off has no observable effect either way, and adding them does not
    # prevent the reap. What actually keeps Edge resident is that THIS script
    # is run as a background task with --wait, so it never returns. See the
    # module docstring.
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(cmd, creationflags=flags)

    info = wait_port(args.port)
    if info:
        print("CDP UP: %s" % info.get("Browser"))
        print("ws: %s" % info.get("webSocketDebuggerUrl"))
    else:
        print("CDP DOWN: port %d never started listening" % args.port)
        print(" => Chromium refused to open the debug port for this profile")

    if args.wait:
        while True:
            time.sleep(5)


if __name__ == "__main__":
    main()
