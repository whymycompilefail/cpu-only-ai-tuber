// ==UserScript==
// @name         Danmaku -> Local VTuber (bridge forwarder)
// @namespace    local/ai-edge
// @version      1.0
// @description  Forward live chat from ANY site to a local danmaku bridge by
//               watching the DOM. No platform API, no keys, no approval --
//               the chat is already rendered on your screen, we just copy it.
// @match        *://live.bilibili.com/*
// @match        *://*.douyu.com/*
// @match        *://*.huya.com/*
// @match        *://live.douyin.com/*
// @match        *://*.kuaishou.com/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// ==/UserScript==

/*
 * Install: Tampermonkey/Violentmonkey -> New script -> paste this.
 * Then open your live room page (the one where you see chat, e.g. the
 * streaming dashboard) and it starts forwarding.
 *
 * Why DOM instead of an API:
 *   platforms restrict chat APIs (keys, review, quotas, or none at all), but
 *   they all *render* chat into your own browser. Watching the DOM works on
 *   every platform with a web chat and needs no permission from anyone.
 *   Trade-off: if a platform redesigns its markup, the selectors below need
 *   updating. That is a 1-line fix, not an architecture change.
 */
(function () {
  "use strict";

  var BRIDGE = "http://127.0.0.1:8765/danmaku";

  // Ordered: specific first, generic fallbacks last. Add your platform here.
  var SELECTORS = [
    ".danmaku-item-container .danmaku-content",   // bilibili (new)
    "#chat-items .chat-item .danmaku-content",    // bilibili
    "#js-barrage-list .barrage-item",             // douyu
    "#msg-list .msg-item .msg-content",           // huya
    ".webcast-chatroom___item .webcast-chatroom___content", // douyin
    ".chat-item",                                 // generic
    "[class*=danmaku]",
    "[class*=barrage]",
  ];

  var seen = [];                 // recent texts, for dedup
  var SEEN_MAX = 200;
  var queue = [];
  var flushing = false;

  function post(items) {
    var body = JSON.stringify(items);
    var done = function () {};
    if (typeof GM_xmlhttpRequest === "function") {
      // Tampermonkey: no CORS restriction.
      GM_xmlhttpRequest({
        method: "POST",
        url: BRIDGE,
        headers: { "Content-Type": "application/json" },
        data: body,
        onload: done,
        onerror: done,
      });
    } else {
      fetch(BRIDGE, {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json" },
        body: body,
      }).catch(done);
    }
  }

  function flush() {
    if (flushing || !queue.length) return;
    flushing = true;
    var batch = queue.slice();
    queue = [];
    post(batch);
    setTimeout(function () { flushing = false; }, 200);
  }

  function handle(text) {
    text = (text || "").trim();
    if (!text || text.length > 120) return;
    if (seen.indexOf(text) >= 0) return;   // the same node twice, or a re-render
    seen.push(text);
    if (seen.length > SEEN_MAX) seen.shift();
    queue.push({ user: "viewer", text: text, kind: "chat" });
  }

  function scan(root) {
    if (!root || root.nodeType !== 1) return;
    for (var i = 0; i < SELECTORS.length; i++) {
      var nodes = root.querySelectorAll(SELECTORS[i]);
      if (!nodes.length) continue;
      for (var j = 0; j < nodes.length; j++) {
        handle(nodes[j].textContent);
      }
      return;                              // first matching selector wins
    }
  }

  var observer = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var added = records[i].addedNodes;
      for (var j = 0; j < added.length; j++) {
        scan(added[j]);
      }
    }
    flush();
  });

  observer.observe(document.body, { childList: true, subtree: true });
  console.log("[danmaku] forwarding to " + BRIDGE);
})();
