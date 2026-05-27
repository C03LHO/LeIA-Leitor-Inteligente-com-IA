(function () {
  const handlers = new Map();

  function on(combo, handler) {
    handlers.set(combo, handler);
  }

  function fmt(e) {
    const parts = [];
    if (e.shiftKey) parts.push("Shift");
    if (e.ctrlKey || e.metaKey) parts.push("Mod");
    if (e.altKey) parts.push("Alt");
    parts.push(e.key);
    return parts.join("+");
  }

  function isTyping(target) {
    if (!target) return false;
    const tag = (target.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || target.isContentEditable;
  }

  function init() {
    document.addEventListener("keydown", (e) => {
      if (isTyping(e.target)) return;
      const combo = fmt(e);
      const handler = handlers.get(combo);
      if (handler) {
        e.preventDefault();
        handler(e);
      }
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.shortcuts = { on, init };
})();
