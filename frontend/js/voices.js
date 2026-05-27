(function () {
  const state = {
    voices: [],
    selectedId: null,
    previewAudio: null,
    previewingId: null,
  };

  async function refresh() {
    try {
      const r = await window.LeIA.api.getJSON("/api/voices");
      state.voices = r.voices || [];
      render();
      updateVoiceLabel();
    } catch (e) {
      window.LeIA.toast("Falha ao carregar vozes: " + e.message, "danger");
    }
  }

  function updateVoiceLabel() {
    const v = state.voices.find((x) => x.id === state.selectedId);
    if (v) document.getElementById("voice-label").textContent = v.name;
  }

  function selectVoice(id) {
    state.selectedId = id;
    const v = state.voices.find((x) => x.id === id);
    if (v) {
      window.LeIA.player.setVoice(id, v.name);
    }
    render();
  }

  function stopPreview() {
    if (state.previewAudio) {
      state.previewAudio.pause();
      state.previewAudio = null;
    }
    state.previewingId = null;
    document.querySelectorAll(".voice-preview-btn").forEach((b) => b.classList.remove("playing"));
  }

  async function playPreview(id) {
    if (state.previewingId === id) { stopPreview(); return; }
    stopPreview();
    state.previewingId = id;
    document.querySelectorAll(`.voice-preview-btn[data-id="${id}"]`).forEach((b) =>
      b.classList.add("playing")
    );
    try {
      const url = window.LeIA.api.previewVoiceURL(id);
      state.previewAudio = new Audio(url);
      state.previewAudio.onended = () => stopPreview();
      state.previewAudio.onerror = () => {
        stopPreview();
        window.LeIA.toast("Falha no preview", "danger");
      };
      await state.previewAudio.play();
    } catch (e) {
      stopPreview();
      window.LeIA.toast("Falha no preview: " + e.message, "danger");
    }
  }

  async function removeVoice(id) {
    if (!confirm("Remover esta voz personalizada?")) return;
    try {
      await window.LeIA.api.del(`/api/voices/${id}`);
      if (state.selectedId === id) {
        state.selectedId = "ana_florence";
        window.LeIA.player.setVoice("ana_florence", "Ana");
      }
      await refresh();
    } catch (e) {
      window.LeIA.toast("Falha ao remover: " + e.message, "danger");
    }
  }

  async function uploadVoice(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".wav")) {
      window.LeIA.toast("Envie um arquivo .wav", "warning");
      return;
    }
    const name = prompt("Nome da voz:", file.name.replace(/\.wav$/i, ""));
    if (!name) return;
    try {
      window.LeIA.toast("Enviando voz…", "info");
      await window.LeIA.api.uploadFile("/api/voices/upload", file, null, { name });
      window.LeIA.toast("Voz adicionada ✓", "success");
      await refresh();
    } catch (e) {
      window.LeIA.toast("Falha: " + e.message, "danger");
    }
  }

  function render() {
    const wrap = document.getElementById("voices-list");
    if (!wrap) return;
    const embedded = state.voices.filter((v) => !v.custom);
    const custom = state.voices.filter((v) => v.custom);
    wrap.innerHTML = "";

    function renderGroup(label, items) {
      if (items.length === 0) return;
      const lbl = document.createElement("div");
      lbl.className = "voices-group-label";
      lbl.textContent = label;
      wrap.appendChild(lbl);
      items.forEach((v) => {
        const item = document.createElement("div");
        item.className = "voice-item" + (v.id === state.selectedId ? " selected" : "");
        item.innerHTML = `
          <div class="voice-radio"></div>
          <div class="voice-meta">
            <div class="voice-name">${escapeHTML(v.name)}</div>
            <div class="voice-style">${escapeHTML(v.style || "")}</div>
            <div class="voice-desc">${escapeHTML(v.description || "")}</div>
          </div>
          <button class="voice-preview-btn" data-id="${v.id}" title="Preview">▶</button>
          ${v.custom ? `<button class="voice-delete-btn" data-id="${v.id}" title="Remover">🗑</button>` : `<div></div>`}
        `;
        item.addEventListener("click", (e) => {
          if (e.target.closest(".voice-preview-btn") || e.target.closest(".voice-delete-btn")) return;
          selectVoice(v.id);
        });
        item.querySelector(".voice-preview-btn").addEventListener("click", (e) => {
          e.stopPropagation();
          playPreview(v.id);
        });
        const delBtn = item.querySelector(".voice-delete-btn");
        if (delBtn) delBtn.addEventListener("click", (e) => { e.stopPropagation(); removeVoice(v.id); });
        wrap.appendChild(item);
      });
    }

    renderGroup("Embutidas", embedded);
    renderGroup("Personalizadas", custom);
  }

  function escapeHTML(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function initVoices() {
    try {
      const v = localStorage.getItem("leia.voice");
      state.selectedId = v || "ana_florence";
    } catch { state.selectedId = "ana_florence"; }
    window.LeIA.player.setVoice(state.selectedId, "");

    const btn = document.getElementById("btn-voice");
    const pop = document.getElementById("voices-popover");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (pop.classList.contains("open")) {
        pop.classList.remove("open");
        stopPreview();
      } else {
        const rect = btn.getBoundingClientRect();
        pop.style.left = `${Math.max(8, rect.left - 200)}px`;
        pop.style.bottom = `calc(100vh - ${rect.top - 8}px)`;
        pop.classList.add("open");
      }
    });
    document.addEventListener("click", (e) => {
      if (!pop.contains(e.target) && e.target !== btn) {
        if (pop.classList.contains("open")) {
          pop.classList.remove("open");
          stopPreview();
        }
      }
    });

    const fileInput = document.getElementById("voice-file-input");
    document.getElementById("btn-upload-voice").addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) uploadVoice(fileInput.files[0]);
      fileInput.value = "";
    });

    refresh();
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.voices = { initVoices, refresh, selectVoice, state };
})();
