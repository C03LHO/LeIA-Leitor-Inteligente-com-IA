(function () {
  function toast(message, variant = "info") {
    const container = document.getElementById("toast-container");
    const el = document.createElement("div");
    el.className = `toast align-items-center text-bg-${variant} border-0 show`;
    el.setAttribute("role", "alert");
    el.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto"></button>
      </div>
    `;
    el.querySelector(".btn-close").addEventListener("click", () => el.remove());
    container.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  async function refreshHardwareBadge() {
    const badge = document.getElementById("hw-badge");
    try {
      const status = await window.LeIA.api.getJSON("/api/system/status");
      const hw = status.hardware;
      if (hw.cuda_available) {
        badge.className = "badge bg-success";
        badge.textContent = `GPU: ${hw.gpu_name || "CUDA"}`;
      } else {
        badge.className = "badge bg-warning";
        badge.textContent = "Modo CPU — síntese mais lenta";
      }
    } catch {
      badge.className = "badge bg-secondary";
      badge.textContent = "status indisponível";
    }
  }

  function onDocumentLoaded(doc) {
    window.LeIA.reader.renderDocument(doc);
    toast("✓ Texto extraído e limpo", "success");
  }

  function closeDocument() {
    window.LeIA.player.stop();
    window.LeIA.reader.reset();
  }

  document.addEventListener("DOMContentLoaded", () => {
    window.LeIA.toast = toast;
    window.LeIA.onDocumentLoaded = onDocumentLoaded;
    window.LeIA.initUpload();
    window.LeIA.player.initPlayer();
    document
      .getElementById("btn-close-doc")
      .addEventListener("click", closeDocument);
    refreshHardwareBadge();
  });
})();
