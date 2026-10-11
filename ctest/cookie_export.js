/*
 * cookie_export.js -- paste into DevTools Console ON A bilibili PAGE
 *                     (any bilibili page you are logged in on).
 *
 * Why this exists
 * ---------------
 * `ctest/blive_probe.py --source bilibili` (the blivedm direct route) starts by
 * calling two anonymous HTTP APIs. Anonymous calls very often come back
 * `{"code":-352}`, which reads like "your IP is banned" but usually just means
 * "no browser session / no fingerprint cookies". Supplying cookies can make it
 * succeed -- and that route needs no browser tab running during your stream.
 *
 * Usage
 * -----
 *   F12 -> Console -> paste -> Enter. It writes the cookie string to your
 *   clipboard AND prints it. Save it to ctest/bili_cookie.txt, then:
 *
 *     Open-LLM-VTuber/.venv/Scripts/python.exe ctest/blive_probe.py <房号> \
 *         --cookie-file ctest/bili_cookie.txt
 *
 * Least-privilege order (try in this order, stop at the first that works)
 * ----------------------------------------------------------------------
 *   STEP 1  what this script prints from `document.cookie` alone.
 *           Usually contains buvid3 / b_nut / b_lsid -- which is most of what
 *           the anti-bot check wants. NO login token involved. Try this first.
 *   STEP 2  only if step 1 still gives -352: add SESSDATA by hand (see below).
 *           SESSDATA is full account authority. Prefer doing this from a THROWAWAY
 *           account, not your main one.
 *
 * How to add SESSDATA manually (it is HttpOnly, so document.cookie cannot see it)
 * -----------------------------------------------------------------------------
 *   F12 -> Application -> Storage -> Cookies -> https://www.bilibili.com
 *   -> find SESSDATA -> copy its Value -> append to the file as:
 *        SESSDATA=<粘贴的值>
 *
 * Privacy
 * -------
 * ctest/bili_cookie.txt is already in .gitignore -- it must never be committed,
 * screenshotted into a repo, or shared. If SESSDATA is in it, treat it like a
 * password: anyone holding it can act as that account.
 */
(function () {
  "use strict";

  var raw = document.cookie;
  if (!raw) {
    console.log("[cookie] document.cookie is empty here -- open this Console "
      + "on https://www.bilibili.com or https://live.bilibili.com instead.");
    return;
  }

  // Which ones actually matter, roughly in order of usefulness to the check.
  var WANTED = ["buvid3", "buvid4", "b_nut", "b_lsid", "bili_jct",
                "DedeUserID", "DedeUserID__ckMd5", "sid", "fingerprint",
                "buvid_fp", "bmg_af_switch", "bmg_src_def_domain"];
  var jar = {};
  raw.split(";").forEach(function (part) {
    var i = part.indexOf("=");
    if (i < 0) return;
    jar[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  });

  var present = WANTED.filter(function (k) { return jar[k]; });
  var hasSess = Object.keys(jar).some(function (k) {
    return /SESSDATA/i.test(k);
  });

  // Print the FULL jar: we do not know exactly which combination satisfies the
  // check, and guessing wrong wastes a round trip.
  console.log("[cookie] === 复制下面这整段，存到 ctest/bili_cookie.txt ===");
  console.log(raw);
  console.log("[cookie] ==================================================");
  console.log("[cookie] 找到的指纹 cookie:", present.join(", ") || "(none)");
  console.log("[cookie] SESSDATA 可见吗:", hasSess,
    "(正常情况应该是 false——它是 HttpOnly，需要从 Application 面板手抄)");
  console.log("[cookie] 建议：先用上面这段去跑 probe；仍报 -352 再按文件头说明加 SESSDATA。");

  try {
    navigator.clipboard.writeText(raw);
    console.log("[cookie] 已复制到剪贴板。");
  } catch (e) {
    console.log("[cookie] 剪贴板写入失败，手动复制上面那段即可。");
  }

  // Second best: offer it as a download so nothing has to be copied by hand.
  try {
    var a = document.createElement("a");
    a.href = "data:text/plain;charset=utf-8," + encodeURIComponent(raw);
    a.download = "bili_cookie.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    console.log("[cookie] 也已尝试触发下载 bili_cookie.txt（可能被浏览器拦，看提示）。");
  } catch (e) { /* ignore */ }
})();
