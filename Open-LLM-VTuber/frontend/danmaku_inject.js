/*
 * danmaku_inject.js -- lets a headless danmaku bridge speak through THIS page.
 *
 * Why this exists
 * ---------------
 * The backend does NOT broadcast.  A reply is delivered only to the WebSocket
 * connection that asked the question (verified: ctest/test_cross_client.py --
 * client B observed zero audio while client A talked).  So the obvious design,
 * "bridge opens its own /client-ws and posts danmaku", produces a reply that
 * nobody can see or hear: the Live2D model stays idle and no audio plays.
 *
 * The audience sees THIS page, so the danmaku must travel over THIS page's
 * socket.  This script:
 *   1. patches window.WebSocket before the app bundle runs, so we can capture
 *      the page's own /client-ws instance,
 *   2. connects back to the danmaku bridge,
 *   3. relays "the AI finished talking" events so the bridge knows when it is
 *      free to feed the next danmaku,
 *   4. on the bridge's command, writes {"type":"text-input"} into the page
 *      socket -- exactly as if the user had typed it.
 *
 * The page keeps handling playback itself, including the
 * "frontend-playback-complete" handshake the backend blocks on.
 *
 * Must be loaded BEFORE the app bundle: the bundle is type="module" (deferred),
 * a classic script is not, so putting this first in <head> is enough.
 */
(function () {
  "use strict";

  var BRIDGE_PORT = 8765;
  var BRIDGE_URL = "ws://127.0.0.1:" + BRIDGE_PORT + "/inject";

  var Native = window.WebSocket;
  var pageWS = null;
  var bridge = null;

  function log(msg) {
    console.log("[danmaku-inject] " + msg);
  }

  var retryTimer = null;
  // A ws:// to 127.0.0.1 can sit in CONNECTING forever when the browser has to
  // resolve a proxy PAC first: neither onopen nor onerror fires, and a retry
  // that only hangs off onclose therefore never happens. The bridge then looks
  // "not attached" with no error anywhere. This watchdog forces the issue.
  var HANDSHAKE_TIMEOUT_MS = 3000;

  // Keep-alive. The tab we live in is normally NOT the focused one -- the
  // focused tab is whichever one is being captured -- so Chrome throttles our
  // timers and eventually freezes the page. Nothing here runs then, including
  // the retry timer above, and the tab stops answering the bridge for minutes
  // at a time while still looking connected. A stalled keepalive is the only
  // visible symptom of that, so it has to shout.
  var keepaliveTimer = null;
  var lastKeepaliveAck = 0;

  function startKeepalive() {
    if (keepaliveTimer) return;
    keepaliveTimer = setInterval(function () {
      if (!bridge || bridge.readyState !== 1) return;
      try {
        bridge.send(JSON.stringify({ ping: Date.now() }));
      } catch (e) {}
      if (lastKeepaliveAck && Date.now() - lastKeepaliveAck > 9000) {
        log("KEEPALIVE STALLED " + (Date.now() - lastKeepaliveAck) +
            "ms -- page is being throttled/frozen");
      }
    }, 3000);
  }

  function scheduleRetry() {
    if (retryTimer) return;
    retryTimer = setTimeout(function () {
      retryTimer = null;
      connectBridge();
    }, 2000);
  }

  function connectBridge() {
    var opened = false;
    try {
      bridge = new Native(BRIDGE_URL);
    } catch (e) {
      log("bridge construct failed: " + e);
      scheduleRetry();
      return;
    }
    bridge.onopen = function () {
      opened = true;
      log("bridge connected");
      bridge.send(JSON.stringify({ hello: true }));
      startKeepalive();
    };
    bridge.onmessage = function (ev) {
      var m;
      try {
        m = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      // Any traffic proves the page is still running. Acknowledging every ~3s
      // keeps this tab out of Chrome's background throttling.
      if (m.pong) {
        lastKeepaliveAck = Date.now();
        return;
      }
      if (!m.send) return;
      if (!pageWS || pageWS.readyState !== 1) {
        log("page socket not ready, dropping: " + m.send);
        return;
      }
      pageWS.send(JSON.stringify({ type: "text-input", text: m.send }));
      log("sent -> " + m.send);
    };
    bridge.onclose = function () {
      log("bridge lost, retrying in 2s");
      scheduleRetry();
    };
    bridge.onerror = function () {
      log("bridge error, retrying");
      scheduleRetry();
    };
    setTimeout(function () {
      if (opened) return;
      var st = bridge ? bridge.readyState : -1;
      log("handshake stalled (readyState=" + st + "), forcing retry");
      try {
        bridge.close();
      } catch (e) {}
      scheduleRetry();
    }, HANDSHAKE_TIMEOUT_MS);
  }

  function hookPageSocket(ws) {
    pageWS = ws;
    log("captured page socket");
    // addEventListener stacks on top of the app's own handlers -- we only
    // observe, we never consume or alter the app's messages.
    ws.addEventListener("message", function (ev) {
      if (!bridge || bridge.readyState !== 1) return;
      var m;
      try {
        m = JSON.parse(ev.data);
      } catch (e) {
        return;
      }
      var event = null;
      if (m.type === "backend-synth-complete") {
        event = "backend-synth-complete";
      } else if (m.type === "control" && m.text === "conversation-chain-end") {
        event = "conversation-chain-end";
      }
      if (event) {
        bridge.send(JSON.stringify({ event: event }));
      }
    });
  }

  window.WebSocket = new Proxy(Native, {
    construct: function (target, args) {
      var ws = Reflect.construct(target, args);
      var url = String(args[0] || "");
      if (url.indexOf("client-ws") >= 0) {
        hookPageSocket(ws);
      }
      return ws;
    }
  });
  log("patch installed");
  // DO NOT re-assign window.WebSocket.prototype here. A Proxy without a `set`
  // trap forwards the write to the native constructor, whose `prototype` is
  // read-only in strict mode -- the assignment throws TypeError, which used to
  // abort this IIFE before connectBridge() ever ran. That is why the page
  // looked perfectly healthy while the bridge was never attached: no WS to
  // :8765 was ever attempted and nothing logged an error.
  // Static constants (CONNECTING/OPEN/...) already resolve: the proxy has no
  // `get` trap either, so reads fall through to the native constructor.

  connectBridge();
})();
