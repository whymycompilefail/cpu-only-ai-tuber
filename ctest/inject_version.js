(async function () {
  var r = await fetch('./danmaku_inject.js', {cache: 'no-store'});
  var t = await r.text();
  return JSON.stringify({
    len: t.length,
    has_watchdog: t.indexOf('handshake stalled') >= 0,
    has_schedule_retry: t.indexOf('scheduleRetry') >= 0,
    head: t.slice(0, 60)
  });
})()
