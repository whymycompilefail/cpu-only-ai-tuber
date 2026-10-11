#!/usr/bin/env python3
"""Pull your bilibili cookies straight out of Chrome/Edge -- no DevTools needed.

    Open-LLM-VTuber/.venv/Scripts/python.exe ctest/grab_browser_cookies.py

Why this exists
---------------
Getting cookies "the normal way" means opening DevTools and pasting a script
into the Console. That asks a lot of someone mid-stream: F12 is often Fn-locked
or captured by vendor software on laptops. But if you are logged in, the cookies
are already sitting in a SQLite file on this machine -- so just read them.

This is the whole difference between the DOM route and the blivedm route: the
token APIs answer `code=-352` to anonymous callers, and supplying real cookies
often clears it. Direct works without keeping a browser tab open.

Privacy
-------
The output file may contain SESSDATA, which is full account authority on bilibili.
It is written to ctest/bili_cookie.txt, which is already gitignored. Never commit
it, screenshot it, or send it to anyone (including an agent -- if something needs
sharing, share only whether the probe succeeded).

Requires the browser to have touched https://www.bilibili.com recently while
logged in. Chrome may need to be closed; if the DB is locked you will be told.

Dependency is not preinstalled:
    python -m pip install --target <dir> browser-cookie3
then either pass --deps <dir> or install it into the venv proper.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DOMAIN = ".bilibili.com"
# What the anti-bot check mostly cares about; anything else is a bonus.
INTERESTING = ("buvid3", "buvid4", "b_nut", "b_lsid", "buvid_fp", "fingerprint",
               "bili_jct", "DedeUserID", "sid", "SESSDATA")


def browsers() -> list[str]:
    return ["edge", "chrome", "chromium", "firefox"]


def try_pull(name: str):
    try:
        import browser_cookie3  # noqa: PLC0415 - loaded late on purpose
    except ImportError:
        return None, "browser_cookie3 not installed"
    fn = getattr(browser_cookie3, name, None)
    if fn is None:
        return None, "no such backend"
    try:
        cj = fn(domain_name=DOMAIN)
    except Exception as e:  # noqa: BLE001 - any failure just means "try next"
        return None, f"{type(e).__name__}: {str(e)[:120]}"
    items = list(cj) if isinstance(cj, http.cookiejar.CookieJar) else []
    return items, None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deps", default="",
                   help="directory holding browser_cookie3 (from pip --target)")
    p.add_argument("--out", default="ctest/bili_cookie.txt")
    a = p.parse_args()
    if a.deps:
        sys.path.insert(0, a.deps)

    found: dict[str, str] = {}
    tried: list[tuple[str, str]] = []
    for name in browsers():
        items, err = try_pull(name)
        if err:
            tried.append((name, err))
            continue
        if not items:
            tried.append((name, "no bilibili cookies"))
            continue
        for c in items:
            found[c.name] = c.value
        tried.append((name, f"{len(items)} cookies"))
        break  # first browser that actually has them is enough

    print("=" * 64)
    print("browser cookie pull")
    print("=" * 64)
    for name, msg in tried:
        print(f"  {name:<10} {msg}")

    if not found:
        print("\n没有读到任何 bilibili cookie。可能的原因：")
        print("  - 浏览器从未登录过 bilibili（或换过配置文件）")
        print("  - 浏览器正在运行且锁住了 cookie 库 —— 关掉浏览器再试")
        print("  - Chrome/Edge 新版加密（AppBound），需要更高版本 browser_cookie3")
        return 1

    have = [k for k in INTERESTING if k in found]
    print(f"\n共 {len(found)} 个 cookie，其中关键项命中：{', '.join(have) or '(无)'}")
    print(f"SESSDATA 是否读到: {'SESSDATA' in found}")

    out_path = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("; ".join(f"{k}={v}" for k, v in found.items()))
    print(f"\n已写入 {out_path}")
    print("注意：这个文件等同账号口令，已在 .gitignore 中，别提交、别分享。")
    print("\n下一步：")
    print(f"  Open-LLM-VTuber/.venv/Scripts/python.exe ctest/blive_probe.py "
          f"<房号> --cookie-file {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
