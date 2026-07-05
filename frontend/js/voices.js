(function () {
  const state = {
    voices: [],
    selectedId: null,
    previewAudio: null,
    previewingId: null,
  };

  function escapeHTML(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  async function refresh() {
    try {
      const r = await window.LeIA.api.getJSON("/api/voices");
      state.voices = r.voices || [];
      if (!state.selectedId) state.selectedId = r.active || (state.voices[0] && state.voices[0].id);
      // Mantém o player em sincronia com a voz ativa e, quando não há escolha
      // salva, adota o padrão do sistema (hoje o Damião).
      const sv = state.voices.find((x) => x.id === state.selectedId);
      if (sv && window.LeIA.player && window.LeIA.player.setVoice) {
        window.LeIA.player.setVoice(state.selectedId, sv.name);
      }
      render();
      updateVoiceLabel();
    } catch (e) {
      window.LeIA.toast("Falha ao carregar vozes: " + e.message, "danger");
    }
  }

  function updateVoiceLabel() {
    const v = state.voices.find((x) => x.id === state.selectedId);
    const el = document.getElementById("voice-label");
    if (v && el) el.textContent = v.name;
  }

  async function selectVoice(id) {
    state.selectedId = id;
    const v = state.voices.find((x) => x.id === id);
    if (v && window.LeIA.player) window.LeIA.player.setVoice(id, v.name);
    try { localStorage.setItem("leia.voice", id); } catch {}
    render();
    updateVoiceLabel();
    // Persiste no servidor → a PREPARAÇÃO de áudio usa esta voz.
    try { await window.LeIA.api.postJSON("/api/voices/active", { voice: id }); } catch {}
    if (v) window.LeIA.toast(`🎙 Voz: ${v.name}`, "success");
  }

  function stopPreview() {
    if (state.previewAudio) { state.previewAudio.pause(); state.previewAudio = null; }
    state.previewingId = null;
    document.querySelectorAll(".voice-preview-btn").forEach((b) => b.classList.remove("playing"));
  }

  async function playPreview(id) {
    if (state.previewingId === id) { stopPreview(); return; }
    stopPreview();
    state.previewingId = id;
    document.querySelectorAll(`.voice-preview-btn[data-id="${id}"]`).forEach((b) => b.classList.add("loading"));
    try {
      // POST (gera/serve o preview cacheado) → toca o WAV.
      const resp = await fetch(`/api/voices/${encodeURIComponent(id)}/preview`, { method: "POST" });
      if (!resp.ok) throw new Error(await resp.text());
      const url = URL.createObjectURL(await resp.blob());
      document.querySelectorAll(`.voice-preview-btn[data-id="${id}"]`).forEach((b) => { b.classList.remove("loading"); b.classList.add("playing"); });
      state.previewAudio = new Audio(url);
      state.previewAudio.onended = () => { stopPreview(); URL.revokeObjectURL(url); };
      state.previewAudio.onerror = () => { stopPreview(); window.LeIA.toast("Falha no preview", "danger"); };
      await state.previewAudio.play();
    } catch (e) {
      stopPreview();
      window.LeIA.toast("Falha no preview: " + (e.message || e), "danger");
    }
  }

  function voiceItem(v) {
    const item = document.createElement("div");
    item.className = "voice-item" + (v.id === state.selectedId ? " selected" : "") + (v.recommended ? " recommended" : "");
    item.innerHTML = `
      <div class="voice-radio"></div>
      <div class="voice-meta">
        <div class="voice-name">${escapeHTML(v.name)}${v.recommended ? '<span class="voice-badge">recomendada</span>' : ""}</div>
        <div class="voice-style">${escapeHTML(v.gender || "")}${v.style ? " · " + escapeHTML(v.style) : ""}</div>
        <div class="voice-desc">${escapeHTML(v.description || "")}</div>
      </div>
      <button class="voice-preview-btn" data-id="${v.id}" title="Ouvir amostra">▶</button>`;
    item.addEventListener("click", (e) => {
      if (e.target.closest(".voice-preview-btn")) return;
      selectVoice(v.id);
    });
    item.querySelector(".voice-preview-btn").addEventListener("click", (e) => { e.stopPropagation(); playPreview(v.id); });
    return item;
  }

  function render() {
    ["voices-list", "voices-settings-list"].forEach((wid) => {
      const wrap = document.getElementById(wid);
      if (!wrap) return;
      wrap.innerHTML = "";
      state.voices.forEach((v) => wrap.appendChild(voiceItem(v)));
    });
  }

  function initVoices() {
    // Migração única: o Damião virou a voz principal (v1.6.5). Quem já tinha uma
    // voz salva é movido UMA vez para o novo padrão; escolhas futuras são mantidas.
    try {
      if (!localStorage.getItem("leia.voiceMigratedV165")) {
        localStorage.removeItem("leia.voice");
        localStorage.setItem("leia.voiceMigratedV165", "1");
      }
    } catch {}
    try { state.selectedId = localStorage.getItem("leia.voice") || null; } catch { state.selectedId = null; }

    const btn = document.getElementById("btn-voice");
    const pop = document.getElementById("voices-popover");
    if (btn && pop) {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (pop.classList.contains("open")) { pop.classList.remove("open"); stopPreview(); }
        else {
          const rect = btn.getBoundingClientRect();
          pop.style.left = `${Math.max(8, rect.left - 200)}px`;
          pop.style.bottom = `calc(100vh - ${rect.top - 8}px)`;
          pop.classList.add("open");
        }
      });
      document.addEventListener("click", (e) => {
        if (!pop.contains(e.target) && e.target !== btn && pop.classList.contains("open")) {
          pop.classList.remove("open"); stopPreview();
        }
      });
    }
    refresh();
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.voices = { initVoices, refresh, selectVoice, state };
})();
