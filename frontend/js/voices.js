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
    const el = document.getElementById("voice-label");
    if (!el) return;
    if (window.LeIA.synced && window.LeIA.synced.isActive()) { el.textContent = "Voz humana"; return; }
    const v = state.voices.find((x) => x.id === state.selectedId);
    if (v) el.textContent = v.name;
  }

  async function selectVoice(id) {
    // escolher uma voz de IA sai do modo "áudio humano importado"
    if (window.LeIA.synced && window.LeIA.synced.isActive()) window.LeIA.synced.deactivate();
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

  function syncedActive() { return !!(window.LeIA.synced && window.LeIA.synced.isActive()); }

  function audioSourceBlock() {
    const jid = window.LeIA.currentJobId;
    if (!jid) return null;   // sem livro aberto → só vozes de IA
    const st = (window.LeIA.synced && window.LeIA.synced.getStatus)
      ? window.LeIA.synced.getStatus() : { has: false, syncing: false };
    const frag = document.createDocumentFragment();
    const hdr = document.createElement("div");
    hdr.className = "voices-group-label";
    hdr.textContent = "Áudio deste livro";
    frag.appendChild(hdr);

    if (st.syncing) {
      const it = document.createElement("div");
      it.className = "voice-item";
      it.innerHTML = `<div class="spinner" style="width:16px;height:16px;border-width:2px"></div>
        <div class="voice-meta"><div class="voice-name">Sincronizando áudio…</div>
        <div class="voice-desc">${st.pct || 0}% · pode continuar lendo com a voz da IA</div></div>`;
      frag.appendChild(it);
    } else if (st.has) {
      const it = document.createElement("div");
      it.className = "voice-item" + (syncedActive() ? " selected" : "");
      it.innerHTML = `<div class="voice-radio"></div>
        <div class="voice-meta"><div class="voice-name">🎧 Voz humana<span class="voice-badge">seu áudio</span></div>
        <div class="voice-desc">Áudio importado, sincronizado com o texto.</div></div>
        <button class="voice-delete-btn" title="Remover áudio importado">✕</button>`;
      it.addEventListener("click", (e) => { if (e.target.closest(".voice-delete-btn")) return; window.LeIA.synced.activate(); });
      it.querySelector(".voice-delete-btn").addEventListener("click", (e) => { e.stopPropagation(); window.LeIA.synced.removeSync(); });
      frag.appendChild(it);
    }

    const imp = document.createElement("div");
    imp.className = "voice-item";
    imp.innerHTML = `<div class="voice-radio" style="border-style:dashed">＋</div>
      <div class="voice-meta"><div class="voice-name">Importar áudio (voz humana)…</div>
      <div class="voice-desc">Um mp3/m4b que você tem → sincroniza com este livro.</div></div>`;
    imp.addEventListener("click", () => window.LeIA.synced.pickFile());
    frag.appendChild(imp);

    const lab = document.createElement("div");
    lab.className = "voices-group-label";
    lab.textContent = "Vozes da IA";
    frag.appendChild(lab);
    return frag;
  }

  function voiceItem(v) {
    const item = document.createElement("div");
    item.className = "voice-item" + ((!syncedActive() && v.id === state.selectedId) ? " selected" : "") + (v.recommended ? " recommended" : "");
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
      const asb = audioSourceBlock();
      if (asb) wrap.appendChild(asb);
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
  window.LeIA.voices = { initVoices, refresh, render, selectVoice, updateVoiceLabel, state };
})();
