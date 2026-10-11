(async function () {
  var out = {};
  try {
    var r = await fetch('http://127.0.0.1:8765/stats', {cache: 'no-store'});
    out.http = 'OK status=' + r.status + ' body=' + (await r.text()).slice(0, 100);
  } catch (e) {
    out.http = 'FAIL ' + e.name + ': ' + e.message;
  }
  try {
    var p = await fetch('http://127.0.0.1:8765/danmaku', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({user: 'browser_probe', text: 'from page'})
    });
    out.post = 'OK status=' + p.status + ' body=' + (await p.text()).slice(0, 60);
  } catch (e) {
    out.post = 'FAIL ' + e.name + ': ' + e.message;
  }
  out.proxy_hint = navigator.userAgent.slice(0, 0);
  return JSON.stringify(out);
})()
