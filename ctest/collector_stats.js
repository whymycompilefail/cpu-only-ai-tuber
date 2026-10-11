(function () {
  var c = window.__danmakuCollector__;
  if (!c) return "NOT installed";
  return JSON.stringify(c.stats());
})()
