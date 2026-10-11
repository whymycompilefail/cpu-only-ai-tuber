#!/usr/bin/env python3
"""Why does getDanmuInfo answer -352 while getInfoByRoom answers 0?

The two calls differ in endpoint, params, and headers. -352 is B站's generic
"risk control" code, which in practice usually means "this request does not
look like it came from the real web player". So we replay the call with the
exact headers the browser sends, one variable at a time, and report which one
flips the code.

Cookie file: ctest/bili_cookie.txt (gitignored), from ctest/cdp_cookie.py.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

URL = "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo"

UA_CHROME102 = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36")
UA_REAL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0")


def load(path: str) -> dict[str, str]:
    jar: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    for part in raw.replace("\n", ";").split(";"):
        item = part.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            jar[k.strip()] = v.strip()
    return jar


VARIANTS = [
    ("blivedm default", UA_CHROME102, {}, {"id": 0, "type": 0}),
    ("+ referer", UA_CHROME102,
     {"Referer": "https://live.bilibili.com/"}, {"id": 0, "type": 0}),
    ("real UA + referer", UA_REAL,
     {"Referer": "https://live.bilibili.com/",
      "Origin": "https://live.bilibili.com"}, {"id": 0, "type": 0}),
    ("real UA + referer, no type", UA_REAL,
     {"Referer": "https://live.bilibili.com/",
      "Origin": "https://live.bilibili.com"}, {"id": 0}),
    ("real UA + referer, type=0 & wts", UA_REAL,
     {"Referer": "https://live.bilibili.com/",
      "Origin": "https://live.bilibili.com"}, {"id": 0, "type": 0, "wts": 0}),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("room_id", type=int)
    ap.add_argument("--cookie-file", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "bili_cookie.txt"))
    args = ap.parse_args()

    import aiohttp
    jar = load(args.cookie_file)
    print("cookies: %d from %s" % (len(jar), args.cookie_file))
    print()

    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15), cookies=jar) as s:
        for name, ua, headers, params in VARIANTS:
            p = dict(params)
            if "id" in p and p["id"] == 0:
                p["id"] = args.room_id
            if "wts" in p:
                import time
                p["wts"] = int(time.time())
            h = {"User-Agent": ua}
            h.update(headers)
            try:
                async with s.get(URL, headers=h, params=p) as r:
                    data = await r.json(content_type=None)
                    code = data.get("code")
                    print("%-28s code=%-6s %s" % (name, code,
                                                  data.get("message", "")))
                    if code == 0:
                        d = data.get("data") or {}
                        hosts = d.get("host_list") or []
                        print("      => host_list=%d token_len=%d  "
                              "FIRST WORKING VARIANT" % (
                                  len(hosts), len(d.get("token") or "")))
            except Exception as e:
                print("%-28s EXC %s: %s" % (name, type(e).__name__, e))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
