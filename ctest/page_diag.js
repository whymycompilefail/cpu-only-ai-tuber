/*
 * page_diag.js -- paste into DevTools Console ON THE LIVE ROOM PAGE
 *                 (the tab where you can SEE chat scrolling).
 *
 * Why it exists: guessing bilibili's class names is a losing game, and when
 * they change the failure is completely silent -- no errors anywhere, the
 * bridge just never receives anything. This script reports what is actually
 * on your screen instead.
 *
 * Usage:
 *   1. open your own live room page, wait until you see some chat
 *   2. F12 -> Console -> paste this whole file -> Enter
 *   3. wait ~15 seconds, then copy the last JSON block back to the agent
 *
 * It does three independent things, so a failure localises immediately:
 *   A. reachability  -- can this tab POST to the bridge at all?
 *   B. static census -- how many nodes do our current selectors match now?
 *   C. live census   -- what shapes of nodes get ADDED as chat arrives?
 * C is the important one: it names the container actually in use on this page
 * today, whatever bilibili renamed it to.
 */
(function () {
  "use strict";
  var TAG = "[diag]";
  function say() {
    console.log(TAG, Array.prototype.join.call(arguments, " "));
  }

  console.log(TAG, "=== start ===");
  say("url:", location.href);
  say("GM_xmlhttpRequest available:", typeof GM_xmlhttpRequest);
  say("is top frame:", window.top === window.self);

  // ---- A. reachability: can this tab reach the local bridge? --------------
  // Deliberately uses fetch(), which is subject to mixed-content and CORS --
  // exactly what the userscript gets if GM_xmlhttpRequest is unavailable. If
  // this fails, no amount of selector work will help.
  var probe = (function () {
    try {
      return fetch("http://127.0.0.1:8765/danmaku", {
        method: "POST",
        mode: "cors",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify([
          { user: "diag", text: "diag reachability probe", kind: "chat" },
        ]),
      });
    } catch (e) {
      say("A. POST threw immediately:", String(e));
      return null;
    }
  })();
  if (probe) {
    probe.then(function (r) {
      r.text().then(function (t) {
        say("A. POST bridge -> HTTP", r.status, JSON.stringify(t));
      });
    }).catch(function (e) {
      // This is the one that actually matters: blocked means the browser, not
      // the selectors, is stopping us.
      say("A. POST FAILED ->", String(e), "(mixed content or bridge down)");
    });
  }

  // ---- B. static census: what our current list matches right now ---------
  var SELECTORS = [
    ".danmaku-item-container .danmaku-content",
    "#chat-items .chat-item .danmaku-content",
    "#js-barrage-list .barrage-item",
    "#msg-list .msg-item .msg-content",
    ".webcast-chatroom___item .webcast-chatroom___content",
    ".chat-item",
    "[class*=danmaku]",
    "[class*=barrage]",
  ];
  var census = {};
  for (var i = 0; i < SELECTORS.length; i++) {
    try {
      census[SELECTORS[i]] = document.querySelectorAll(SELECTORS[i]).length;
    } catch (e) {
      census[SELECTORS[i]] = "ERR " + e.message;
    }
  }
  say("B. static census:", JSON.stringify(census, null, 1));

  // ---- C. live census: learn what actually gets appended -----------------
  var shapes = {};
  var sample = {};
  function note(node) {
    if (node.nodeType !== 1) return;
    var cls = typeof node.className === "string" ? node.className : "";
    if (!cls) return;
    var key = node.tagName.toLowerCase() + "." + cls.trim().split(/\s+/)[0];
    key = key.slice(0, 60);
    shapes[key] = (shapes[key] || 0) + 1;
    if (!sample[key]) sample[key] = (node.textContent || "").trim().slice(0, 60);
    // One level down too: often the container is generic and the text node
    // lives in a child with the specific class.
    var kids = node.children || [];
    for (var k = 0; k < kids.length && k < 4; k++) {
      note(kids[k]);
    }
  }

  var mo = new MutationObserver(function (records) {
    for (var i = 0; i < records.length; i++) {
      var added = records[i].addedNodes || [];
      for (var j = 0; j < added.length; j++) note(added[j]);
    }
  });
  mo.observe(document.body, { childList: true, subtree: true });
  say("C. watching the DOM for 15s -- please make sure some chat arrives");

  setTimeout(function () {
    mo.disconnect();
    var keys = Object.keys(shapes);
    var top = keys
      .sort(function (a, b) { return shapes[b] - shapes[a]; })
      .slice(0, 15);
    console.log(TAG, "=== nodes added in the last 15s ===");
    for (var i = 0; i < top.length; i++) {
      console.log(
        TAG,
        "   " + String(shapes[top[i]]).padStart(4) + "  " + top[i] +
        "   e.g. " + JSON.stringify(sample[top[i]])
      );
    }
    console.log(TAG, "=== COPY EVERYTHING BELOW ===");
    console.log(
      JSON.stringify({
        url: location.href,
        census: census,
        added: top.map(function (k) { return [k, shapes[k], sample[k]]; }),
      })
    );
    console.log(TAG, "=== done ===");
  }, 15000);
})();
