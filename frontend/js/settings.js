(function () {
  const SIZE_KEY = "leia.reader.size";
  const AUTOPLAY_KEY = "leia.autoplay";
  const CFG_KEY = "leia.cleaning";

  function loadPrefs() {
    try {
      const size = parseInt(localStorage.getItem(SIZE_KEY) || "19", 10);
      window.LeIA.reader.setReaderFontSize(size);
      document.querySelectorAll(".size-preset").forEach((b) => {
        b.classList.toggle("active", parseInt(b.dataset.size, 10) === size);
      });
      const autoplay = localStorage.getItem(AUTOPLAY_KEY) === "1";
      const sw = document.getElementById("toggle-autoplay");
      if (sw) sw.classList.toggle("on", autoplay);
    } catch {}
  }

  function open() { document.getElementById("settings-backdrop").classList.add("open"); refreshSystemInfo(); }
  function close() { document.getElementById("settings-backdrop").classList.remove("open"); }

  function switchTab(name) {
    document.querySelectorAll(".modal-tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === name)
    );
    document.querySelectorAll(".modal-pane").forEach((p) =>
      p.classList.toggle("hidden", p.dataset.pane !== name)
    );
  }

  async function refreshSystemInfo() {
    const wrap = document.getElementById("system-info");
    if (!wrap) return;
    try {
      const s = await window.LeIA.api.getJSON("/api/system/status");
      const hw = s.hardware;
      wrap.innerHTML = `
        <div class="modal-row"><div class="modal-row-label">Versão</div><div>${s.app.version}</div></div>
        <div class="modal-row"><div class="modal-row-label">Dispositivo</div><div>${hw.cuda_available ? "GPU (CUDA)" : "CPU"}</div></div>
        <div class="modal-row"><div class="modal-row-label">GPU</div><div>${hw.gpu_name || "—"}</div></div>
        <div class="modal-row"><div class="modal-row-label">VRAM</div><div>${hw.vram_mb ? hw.vram_mb + " MB" : "—"}</div></div>
        <div class="modal-row"><div class="modal-row-label">TTS carregado</div><div>${s.tts.loaded ? "Sim" : "Não"}</div></div>
      `;
    } catch {}
  }

  function initSettings() {
    document.getElementById("btn-settings").addEventListener("click", open);
    document.getElementById("btn-close-settings").addEventListener("click", close);
    document.getElementById("settings-backdrop").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) close();
    });
    document.querySelectorAll(".modal-tab").forEach((t) => {
      t.addEventListener("click", () => switchTab(t.dataset.tab));
    });

    document.querySelectorAll(".size-preset").forEach((b) => {
      b.addEventListener("click", () => {
        const size = parseInt(b.dataset.size, 10);
        window.LeIA.reader.setReaderFontSize(size);
        document.querySelectorAll(".size-preset").forEach((x) =>
          x.classList.toggle("active", x === b)
        );
      });
    });

    document.querySelectorAll(".switch[data-cfg]").forEach((sw) => {
      const key = `${CFG_KEY}.${sw.dataset.cfg}`;
      const stored = localStorage.getItem(key);
      if (stored !== null) sw.classList.toggle("on", stored === "1");
      sw.addEventListener("click", () => {
        sw.classList.toggle("on");
        try { localStorage.setItem(key, sw.classList.contains("on") ? "1" : "0"); } catch {}
      });
    });

    const ap = document.getElementById("toggle-autoplay");
    if (ap) {
      ap.addEventListener("click", () => {
        ap.classList.toggle("on");
        try { localStorage.setItem(AUTOPLAY_KEY, ap.classList.contains("on") ? "1" : "0"); } catch {}
      });
    }

    window.LeIA.shortcuts.on("Escape", close);
    loadPrefs();
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.settings = { initSettings, open, close };
})();
