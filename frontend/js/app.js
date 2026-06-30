(function () {
  let currentJobId = null;
  let audioPoll = null;   // poll do leitor aberto (gate de play)
  let shelfPoll = null;   // poll da estante (atualiza % das capas)

  let allItems = [];
  let activeCollection = "";
  let searchResults = null; // null = não está buscando
  let searchTimer = null;

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

  function escapeHTML(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  // ~14 caracteres de fala por segundo (pt-BR, 1x) → estimativa do tempo de áudio.
  function fmtDur(secs) {
    secs = Math.max(0, Math.round(secs));
    if (secs < 60) return "< 1 min";
    const m = Math.round(secs / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), mm = m % 60;
    return mm ? `${h} h ${mm} min` : `${h} h`;
  }

  async function refreshHardwareBadge() {
    const badge = document.getElementById("hw-badge");
    try {
      const status = await window.LeIA.api.getJSON("/api/system/status");
      const hw = status.hardware;
      badge.classList.remove("gpu", "cpu");
      if (hw.cuda_available) { badge.classList.add("gpu"); badge.querySelector(".text").textContent = "GPU"; }
      else { badge.classList.add("cpu"); badge.querySelector(".text").textContent = "CPU"; }
    } catch { badge.querySelector(".text").textContent = "—"; }
  }

  // ---------- preparo de áudio (status no topo + gate de play) ----------
  function setPrep(text, cls) {
    const el = document.getElementById("prep-status");
    if (!el) return;
    if (!text) { el.classList.add("hidden"); return; }
    el.className = "prep-status " + (cls || "");
    el.textContent = text;
    el.classList.remove("hidden");
  }

  function stopAudioPoll() { if (audioPoll) { clearTimeout(audioPoll); audioPoll = null; } }

  const PLAY_BUFFER = 5; // frases prontas à frente da posição para liberar o play

  function gatePlayUntilReady(jobId, audioReadyHint) {
    stopAudioPoll();
    if (audioReadyHint) {
      window.LeIA.player.setReady(true);
      setPrep("✓ Narração pronta", "ready");
      setTimeout(() => { if (currentJobId === jobId) setPrep(null); }, 3500);
      return;
    }
    let unlocked = false;
    window.LeIA.player.setReady(false);
    async function tick() {
      if (currentJobId !== jobId) return;
      try {
        const s = await window.LeIA.api.getJSON(`/api/pdf/${jobId}/audio-status`);
        const done = s.done || 0, total = s.total || 0;
        const pct = total ? Math.round((done / total) * 100) : 0;
        if (s.status === "done") {
          window.LeIA.player.setReady(true);
          setPrep("✓ Narração pronta", "ready");
          setTimeout(() => { if (currentJobId === jobId) setPrep(null); }, 3500);
          return;
        }
        if (s.status === "error") {
          setPrep("⚠ Falha ao preparar o áudio — tente reabrir", "preparing");
          audioPoll = setTimeout(tick, 3000);
          return;
        }
        if (!unlocked) {
          const pos = window.LeIA.player.currentIndex();
          if (done >= pos + PLAY_BUFFER || (total && done >= total)) unlocked = true;
        }
        window.LeIA.player.setReady(unlocked);
        setPrep(
          unlocked
            ? `▶ Pode ouvir · preparando o resto (${pct}%)`
            : `⏳ Preparando o início… (${pct}%)`,
          unlocked ? "ready" : "preparing"
        );
        audioPoll = setTimeout(tick, 1500);
      } catch { audioPoll = setTimeout(tick, 3000); }
    }
    tick();
  }

  // ---------- abrir um livro (estante → leitor) ----------
  async function openDoc(jobId, audioReadyHint) {
    try {
      const doc = await window.LeIA.api.getJSON(`/api/pdf/${jobId}/result`);
      currentJobId = jobId;
      window.LeIA.currentJobId = jobId; // para os marcadores
      window.LeIA.reader.renderDocument(doc);
      const saved = parseInt(localStorage.getItem(`leia.progress.${jobId}`) || "-1", 10);
      window.LeIA.player.restorePosition(saved > 0 ? saved : 0);
      if (window.LeIA.player.renderBookmarks) window.LeIA.player.renderBookmarks();
      if (saved > 0) toast("📖 Retomando de onde você parou", "info");
      gatePlayUntilReady(jobId, audioReadyHint);
    } catch (e) {
      toast("Falha ao abrir: " + e.message, "danger");
    }
  }

  // chamado pelo upload: livro novo entra na estante (não abre o leitor)
  function onBookAdded(jobId) {
    currentJobId = null;
    window.LeIA.currentJobId = null;
    window.LeIA.reader.reset();
    refreshLibrary();
    toast("📚 Livro adicionado à estante — preparando a narração.", "success");
  }

  function saveProgress(globalIndex) {
    if (currentJobId == null || globalIndex == null) return;
    try { localStorage.setItem(`leia.progress.${currentJobId}`, String(globalIndex)); } catch {}
  }

  // ---------- início / estante ----------
  function goHome() {
    stopAudioPoll();
    setPrep(null);
    currentJobId = null;
    window.LeIA.currentJobId = null;
    searchResults = null;
    activeCollection = "";
    const si = document.getElementById("library-search");
    if (si) si.value = "";
    window.LeIA.player.stop({ keepHighlight: false });
    window.LeIA.reader.reset();
    refreshLibrary();
  }

  function stopShelfPoll() { if (shelfPoll) { clearTimeout(shelfPoll); shelfPoll = null; } }

  function bookCard(it, snippet) {
    const a = it.audio || {};
    const pct = a.total ? Math.round((a.done / a.total) * 100) : 0;
    const savedIdx = parseInt(localStorage.getItem(`leia.progress.${it.job_id}`) || "-1", 10);
    const readPct = (savedIdx >= 0 && a.total) ? Math.min(100, Math.round((savedIdx / a.total) * 100)) : 0;
    const durStr = it.chars ? "~" + fmtDur(it.chars / 14) + " de áudio" : "";
    const statusLine = it.audio_ready
      ? (readPct > 0 ? `${readPct}% lido` : "pronto para ouvir")
      : `preparando áudio${a.total ? " · " + pct + "%" : "…"}`;
    const card = document.createElement("div");
    card.className = "book" + (it.audio_ready ? " is-ready" : " is-preparing");
    card.innerHTML = `
      <div class="book-cover">
        <div class="book-cover-fallback">📖</div>
        <img class="book-cover-img" src="/api/pdf/${it.job_id}/cover" alt=""
             onload="this.classList.add('loaded')" onerror="this.remove()">
        ${it.audio_ready
          ? `<div class="book-badge">▶</div>`
          : `<div class="book-loading"><div class="spinner"></div><span>${pct}%</span></div>`}
        ${readPct > 0 ? `<div class="book-progress"><div class="book-progress-fill" style="width:${readPct}%"></div></div>` : ""}
      </div>
      <div class="book-title" title="${escapeHTML(it.title || it.filename)}">${escapeHTML(it.title || it.filename)}</div>
      ${it.author ? `<div class="book-author">${escapeHTML(it.author)}</div>` : ""}
      <div class="book-meta">${it.pages || 0} págs${durStr ? " · " + durStr : ""}</div>
      <div class="book-sub">${statusLine}</div>
      ${snippet ? `<div class="book-snippet">“${escapeHTML(snippet)}”</div>` : ""}
      <div class="book-actions">
        <button class="book-act book-collection" title="Mover para coleção">📁</button>
        <button class="book-act book-del" title="Remover da estante">🗑</button>
      </div>
    `;
    card.addEventListener("click", (e) => {
      if (e.target.closest(".book-act")) return;
      openDoc(it.job_id, it.audio_ready);
    });
    card.querySelector(".book-del").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Remover "${it.title || it.filename}" da estante?`)) return;
      try {
        await window.LeIA.api.del(`/api/pdf/${it.job_id}`);
        try { localStorage.removeItem(`leia.progress.${it.job_id}`); } catch {}
        refreshLibrary();
      } catch (err) { toast("Falha ao remover: " + err.message, "danger"); }
    });
    card.querySelector(".book-collection").addEventListener("click", (e) => {
      e.stopPropagation();
      moveToCollection(it);
    });
    return card;
  }

  async function moveToCollection(it) {
    const existing = [...new Set(allItems.map((x) => x.collection).filter(Boolean))];
    const hint = existing.length ? `\nExistentes: ${existing.join(", ")}` : "";
    const name = prompt(`Coleção para "${it.title || it.filename}" (vazio = nenhuma):${hint}`, it.collection || "");
    if (name === null) return;
    try {
      await window.LeIA.api.postJSON(`/api/pdf/${it.job_id}/collection`, { collection: name.trim() });
      refreshLibrary();
    } catch (e) { toast("Falha: " + e.message, "danger"); }
  }

  function renderChips() {
    const wrap = document.getElementById("collection-chips");
    if (!wrap) return;
    const colls = [...new Set(allItems.map((x) => x.collection).filter(Boolean))].sort();
    if (!colls.length || searchResults !== null) { wrap.classList.add("hidden"); return; }
    wrap.classList.remove("hidden");
    wrap.innerHTML = "";
    const mk = (label, val) => {
      const c = document.createElement("button");
      c.className = "chip" + (activeCollection === val ? " active" : "");
      c.textContent = label;
      c.addEventListener("click", () => { activeCollection = val; renderChips(); applyFilter(); });
      return c;
    };
    wrap.appendChild(mk("Todos", ""));
    colls.forEach((c) => wrap.appendChild(mk(c, c)));
  }

  function applyFilter() {
    const wrap = document.getElementById("library-list");
    const empty = document.getElementById("library-empty");
    if (!wrap) return;
    let list;
    if (searchResults !== null) {
      list = searchResults
        .map((r) => ({ item: allItems.find((x) => x.job_id === r.job_id), snippet: r.snippet }))
        .filter((x) => x.item);
    } else {
      list = allItems
        .filter((x) => !activeCollection || x.collection === activeCollection)
        .map((x) => ({ item: x, snippet: null }));
    }
    wrap.innerHTML = "";
    list.forEach(({ item, snippet }) => wrap.appendChild(bookCard(item, snippet)));
    if (empty) empty.classList.toggle("hidden", list.length > 0);
  }

  function doSearch(q) {
    if (searchTimer) clearTimeout(searchTimer);
    if (!q || q.length < 2) { searchResults = null; renderChips(); applyFilter(); return; }
    searchTimer = setTimeout(async () => {
      try {
        const r = await window.LeIA.api.getJSON(`/api/pdf/search?q=${encodeURIComponent(q)}`);
        searchResults = r.results || [];
      } catch { searchResults = []; }
      renderChips();
      applyFilter();
    }, 250);
  }

  async function refreshLibrary() {
    const lib = document.getElementById("library");
    if (!lib) return;
    stopShelfPoll();
    try {
      const r = await window.LeIA.api.getJSON("/api/pdf/library");
      allItems = (r.items || []).sort(
        (a, b) => (b.last_opened || b.created_at || 0) - (a.last_opened || a.created_at || 0)
      );
      const welcome = document.getElementById("view-welcome");
      if (welcome) welcome.classList.toggle("has-books", allItems.length > 0);
      if (!allItems.length) { lib.classList.add("hidden"); return; }
      lib.classList.remove("hidden");
      renderChips();
      applyFilter();
      const anyPreparing = allItems.some((it) => !it.audio_ready);
      const shelfVisible = !welcome.classList.contains("hidden");
      if (anyPreparing && shelfVisible && searchResults === null) shelfPoll = setTimeout(refreshLibrary, 2000);
    } catch { lib.classList.add("hidden"); }
  }

  document.addEventListener("DOMContentLoaded", () => {
    window.LeIA.toast = toast;
    window.LeIA.onBookAdded = onBookAdded;
    window.LeIA.openDoc = openDoc;
    window.LeIA.goHome = goHome;
    window.LeIA.refreshLibrary = refreshLibrary;
    window.LeIA.saveProgress = saveProgress;

    window.LeIA.shortcuts.init();
    window.LeIA.initUpload();
    window.LeIA.player.initPlayer();
    window.LeIA.voices.initVoices();
    window.LeIA.settings.initSettings();

    document.getElementById("btn-close-doc").addEventListener("click", goHome);
    const brand = document.getElementById("brand-home");
    if (brand) brand.addEventListener("click", goHome);
    const si = document.getElementById("library-search");
    if (si) si.addEventListener("input", () => doSearch(si.value.trim()));

    refreshHardwareBadge();
    refreshLibrary();
  });
})();
