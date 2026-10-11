(function () {
  function race(p, ms, label) {
    return Promise.race([
      p,
      new Promise(function (_, rej) {
        setTimeout(function () { rej(new Error(label + ' TIMEOUT')); }, ms);
      })
    ]);
  }
  var results = {};
  // text/plain is a CORS "simple" content type: no preflight is sent, so this
  // isolates "the network never answers" from "the preflight is what hangs".
  var simple = fetch('http://127.0.0.1:8765/danmaku', {
    method: 'POST',
    headers: {'Content-Type': 'text/plain'},
    body: 'plain-probe'
  }).then(function (r) { return 'status=' + r.status; },
          function (e) { return 'ERR ' + e.message; });

  return race(simple, 6000, 'simple').then(function (v) {
    results.simple_post = v;
    return JSON.stringify(results);
  }, function (e) {
    results.simple_post = 'RACE ' + e.message;
    return JSON.stringify(results);
  });
})()
