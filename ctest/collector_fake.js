(function () {
  var c = window.__danmakuCollector__;
  if (!c) return "collector NOT installed";
  var r = c.fake("自测用户", "米粒你好，说句话听听");
  return r + " " + JSON.stringify(c.stats());
})()
