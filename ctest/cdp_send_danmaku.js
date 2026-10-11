/*
 * Type into the real chat box and press the real send button.
 *
 * Why not `ta.value = "..."`: the page is Vue-driven and owns the element's
 * value, so a plain assignment is invisible to it and the send button stays
 * disabled. Going through the prototype's native setter and then firing a
 * bubbling `input` event is what the framework actually listens for.
 */
(function () {
  var TEXT = "米粒米粒，听得到我说话吗？";
  var ta = document.querySelector("textarea.chat-input");
  if (!ta) return JSON.stringify({ok: false, why: "no textarea.chat-input"});

  ta.focus();
  var proto = window.HTMLTextAreaElement.prototype;
  var setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(ta, TEXT);
  ta.dispatchEvent(new Event("input", {bubbles: true}));

  return new Promise(function (resolve) {
    setTimeout(function () {
      var btn = document.querySelector("button.send-btn");
      if (!btn) { resolve(JSON.stringify({ok: false, why: "no send button"})); return; }
      var disabled = btn.disabled ||
                     (btn.className || "").indexOf("disabled") >= 0;
      btn.click();
      setTimeout(function () {
        resolve(JSON.stringify({ok: true, text: TEXT, wasDisabled: !!disabled,
                                valueNow: ta.value}));
      }, 500);
    }, 400);
  });
})()
