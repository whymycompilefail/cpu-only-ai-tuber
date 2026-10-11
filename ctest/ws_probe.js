(function () {
  return new Promise(function (resolve) {
    var settled = false;
    function done(v) { if (!settled) { settled = true; resolve(v); } }
    var ws;
    try {
      ws = new WebSocket('ws://127.0.0.1:8765/inject');
    } catch (e) {
      return done('CONSTRUCT THREW: ' + e.message);
    }
    ws.onopen = function () {
      try { ws.send(JSON.stringify({hello: true})); } catch (e) {}
      done('WS OPEN');
    };
    ws.onerror = function () { done('WS ERROR'); };
    ws.onclose = function (ev) { done('WS CLOSED code=' + ev.code); };
    setTimeout(function () { done('WS TIMEOUT (5s, no event fired)'); }, 5000);
  });
})()
