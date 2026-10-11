/*
 * danmaku_collector.js -- read danmaku out of the live page and HOLD them.
 *
 * Written against the real DOM (see ctest/cdp_struct.py output), not guessed:
 *   <div class="chat-item danmaku-item"
 *        data-uname="用户8256" data-danmaku="主播主播" data-id_str="27cb...">
 * so the sender name comes from data-uname instead of being hardcoded to
 * "viewer", and id_str gives us a stable key for dedupe.
 *
 * Why it buffers instead of posting
 * ---------------------------------
 * The first version POSTed straight to http://127.0.0.1:8765/danmaku. That
 * never got through, and no amount of fixing the server side helped:
 *   - CORS headers (incl. Access-Control-Allow-Private-Network) are correct,
 *     and curl replies 204 to the exact preflight Chrome sends;
 *   - a no-preflight text/plain POST still times out, so it is NOT preflight;
 *   - --proxy-bypass-list and --no-proxy-server do not change it.
 * A public https origin reaching loopback is gated by Chrome's Local Network
 * Access, and the request simply hangs -- no response, no rejection.
 *
 * So the page does no networking at all. It pushes danmaku into a queue and
 * ctest/danmaku_pump.py drains that queue over CDP (a local WebSocket from
 * Python) and POSTs to the bridge itself. Nothing about the page's network
 * policy can break that.
 *
 * Installed over CDP into the live.bilibili.com tab.
 */
(function () {
  "use strict";
  var KEY = "__danmakuCollector__";
  if (window[KEY]) {
    return "already installed: " + JSON.stringify(window[KEY].stats());
  }

  var SELECTOR = ".chat-item.danmaku-item";
  var seen = Object.create(null);
  var queue = [];                 // drained by danmaku_pump.py over CDP
  var buffered = 0;               // total ever queued (never reset)
  var seenCount = 0;

  function push(uname, text) {
    queue.push({user: uname || "viewer", text: text, kind: "chat"});
    buffered++;
    // Bound it: if nobody drains, do not grow without limit.
    if (queue.length > 200) queue.shift();
  }

  function handle(el) {
    if (!el || !el.dataset) return;
    var text = el.dataset.danmaku;
    if (!text) return;
    var key = el.dataset.idStr || el.getAttribute("data-id_str") ||
              (el.dataset.uname + "|" + text);
    if (seen[key]) return;
    seen[key] = 1;
    seenCount++;
    push(el.dataset.uname, text);
  }

  function scan(root) {
    var list = root.querySelectorAll ? root.querySelectorAll(SELECTOR) : [];
    for (var i = 0; i < list.length; i++) handle(list[i]);
  }

  var obs = new MutationObserver(function (muts) {
    for (var i = 0; i < muts.length; i++) {
      var adds = muts[i].addedNodes;
      for (var j = 0; j < adds.length; j++) {
        var n = adds[j];
        if (n.nodeType !== 1) continue;
        if (n.matches && n.matches(SELECTOR)) handle(n);
        scan(n);
      }
    }
  });

  obs.observe(document.body, {childList: true, subtree: true});
  scan(document);                  // catch whatever already rendered

  window[KEY] = {
    stop: function () { obs.disconnect(); return "stopped"; },
    stats: function () { return {queued: queue.length, buffered: buffered,
                                 unique: seenCount}; },
    /* Take everything collected so far and clear it. */
    drain: function () { var out = queue; queue = []; return out; },
    /* test hook: pretend a danmaku arrived without waiting for a real one */
    fake: function (u, t) { push(u, t); return "queued"; }
  };

  return "installed on " + location.href;
})()
