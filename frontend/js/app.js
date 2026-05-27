(function () {
  function toast(message, variant = "info") {
    const stack = document.getElementById("toast-stack");
    const el = document.createElement("div");
    el.className = `toast ${variant}`;
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 200);
    }, 4500);
  }

  async function refreshHardwareBadge() {
    const badge = document.getElementById("hw-badge");
    try {
      const status = await window.LeIA.api.getJSON("/api/system/status");
      const hw = status.hardware;
      badge.classList.remove("gpu", "cpu");
      if (hw.cuda_available) {
        badge.classList.add("gpu");
        badge.querySelector(".text").textContent = "GPU";
      } else {
        badge.classList.add("cpu");
        badge.querySelector(".text").textContent = "CPU";
      }
    } catch {
      badge.querySelector(".text").textContent = "—";
    }
  }

  function onDocumentLoaded(doc) {
    window.LeIA.reader.renderDocument(doc);
    const m = doc.metadata;
    const sum = (m.extracted_chars || 0) + (m.removed_chars || 0);
    const pct = sum > 0 ? ((m.removed_chars / sum) * 100).toFixed(1) : "0.0";
    const reasons = Object.keys(m.removal_reasons || {}).join(", ");
    const reasonsTxt = reasons ? ` (${reasons})` : "";
    toast(`✓ Texto limpo · ${pct}% removido${reasonsTxt}`, "success");

    if (localStorage.getItem("leia.autoplay") === "1") {
      setTimeout(() => window.LeIA.player.toggle(), 300);
    }
  }

  function closeDocument() {
    window.LeIA.player.stop({ keepHighlight: false });
    window.LeIA.reader.reset();
  }

  document.addEventListener("DOMContentLoaded", () => {
    window.LeIA.toast = toast;
    window.LeIA.onDocumentLoaded = onDocumentLoaded;

    window.LeIA.shortcuts.init();
    window.LeIA.initUpload();
    window.LeIA.player.initPlayer();
    window.LeIA.voices.initVoices();
    window.LeIA.settings.initSettings();

    document.getElementById("btn-close-doc").addEventListener("click", closeDocument);
    refreshHardwareBadge();
  });
})();
