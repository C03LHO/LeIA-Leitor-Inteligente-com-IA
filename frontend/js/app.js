(function () {
  let currentJobId = null;
  let audioPoll = null;   // poll do leitor aberto (gate de play)
  let shelfPoll = null;   // poll da estante (atualiza % das capas)
  let queuePoll = null;   // poll da fila de narração

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
    setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 200); }, 4500);
  }

  function escapeHTML(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function fmtDur(secs) {
    secs = Math.max(0, Math.round(secs));
    if (secs < 60) return "< 1 min";
    const m = Math.round(secs / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), mm = m % 60;
    return mm ? `${h} h ${mm} min` : `${h} h`;
  }

  async function showVersion() {
    const el = document.getElementById("app-version");
    if (!el) return;
    try {
      const info = await window.LeIA.api.getJSON("/api");
      el.textContent = "v" + (info.version || "?");
    } catch { el.textContent = ""; }
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
    let requested = false;
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
          refreshQueue();
          return;
        }
        if (s.status === "none") {
          // Ler NÃO gera áudio (não pesa no disco/GPU). A narração é sob demanda:
          // o play gera só o trecho que você ouvir. Para preparar o livro INTEIRO
          // de propósito, use o botão 🎧 na estante.
          window.LeIA.player.setReady(true);
          setPrep("🎧 Narração sob demanda — é só dar play", "");
          setTimeout(() => { if (currentJobId === jobId) setPrep(null); }, 4000);
          return;
        }
        if (s.status === "queued") {
          setPrep(s.position ? `⏳ Na fila (${s.position}º) para a narração` : "⏳ Na fila para a narração", "preparing");
          audioPoll = setTimeout(tick, 1500);
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
        setPrep(unlocked ? `▶ Pode ouvir · preparando o resto (${pct}%)` : `⏳ Preparando o início… (${pct}%)`, unlocked ? "ready" : "preparing");
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
      window.LeIA.currentJobId = jobId;
      window.LeIA.reader.renderDocument(doc);
      let saved = parseInt(localStorage.getItem(`leia.progress.${jobId}`) || "-1", 10);
      // O servidor guarda o progresso em disco — usa o mais avançado dos dois.
      try {
        const sp = await window.LeIA.api.getJSON(`/api/pdf/${jobId}/progress`);
        if (sp && typeof sp.index === "number" && sp.index > saved) saved = sp.index;
      } catch {}
      lastSavedIdx = saved > 0 ? saved : -1;
      window.LeIA.player.restorePosition(saved > 0 ? saved : 0);
      if (window.LeIA.player.renderBookmarks) window.LeIA.player.renderBookmarks();
      if (saved > 0) toast("📖 Retomando de onde você parou", "info");
      gatePlayUntilReady(jobId, audioReadyHint);
    } catch (e) {
      toast("Falha ao abrir: " + e.message, "danger");
    }
  }

  function onBookAdded(jobId) {
    currentJobId = null;
    window.LeIA.currentJobId = null;
    window.LeIA.reader.reset();
    refreshLibrary();
    refreshQueue();
    toast("📚 Livro adicionado à estante.", "success");
  }

  let progressTimer = null;
  let lastSavedIdx = -1;

  function postProgress(jobId, idx, total) {
    if (jobId == null || idx == null || idx < 0) return;
    try {
      const body = JSON.stringify({ index: idx, total: total || 0 });
      // sendBeacon sobrevive ao fechamento da janela (fire-and-forget).
      if (navigator.sendBeacon) {
        navigator.sendBeacon(`/api/pdf/${jobId}/progress`, new Blob([body], { type: "application/json" }));
      } else {
        window.LeIA.api.postJSON(`/api/pdf/${jobId}/progress`, { index: idx, total: total || 0 }).catch(() => {});
      }
    } catch {}
  }

  function totalSentences() {
    const r = window.LeIA.reader && window.LeIA.reader.state;
    return (r && r.sentences && r.sentences.length) || 0;
  }

  // Salva o progresso no localStorage (instantâneo) E no servidor (em disco,
  // com debounce) — assim não se perde por fechamento brusco/queda de energia.
  function saveProgress(globalIndex) {
    if (currentJobId == null || globalIndex == null) return;
    try { localStorage.setItem(`leia.progress.${currentJobId}`, String(globalIndex)); } catch {}
    lastSavedIdx = globalIndex;
    const jid = currentJobId;
    const total = totalSentences();
    if (progressTimer) clearTimeout(progressTimer);
    progressTimer = setTimeout(() => postProgress(jid, globalIndex, total), 2500);
  }

  function flushProgress() {
    if (progressTimer) { clearTimeout(progressTimer); progressTimer = null; }
    if (currentJobId != null && lastSavedIdx >= 0) postProgress(currentJobId, lastSavedIdx, totalSentences());
  }

  // ---------- início / estante ----------
  function goHome() {
    stopAudioPoll();
    setPrep(null);
    const ex = document.getElementById("view-explore");
    if (ex) ex.classList.add("hidden");
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

  async function prepareBook(jobId) {
    try {
      await window.LeIA.api.postJSON(`/api/pdf/${jobId}/prepare`, {});
      toast("🎧 Adicionado à fila de narração.", "success");
      refreshLibrary();
      refreshQueue();
    } catch (e) { toast("Falha: " + e.message, "danger"); }
  }

  function bookCard(it, snippet) {
    const a = it.audio || {};
    const pct = a.total ? Math.round((a.done / a.total) * 100) : 0;
    const savedIdx = parseInt(localStorage.getItem(`leia.progress.${it.job_id}`) || "-1", 10);
    const readPct = (savedIdx >= 0 && a.total) ? Math.min(100, Math.round((savedIdx / a.total) * 100)) : 0;
    const durStr = it.chars ? "~" + fmtDur(it.chars / 14) + " de áudio" : "";
    const st = a.status || (it.audio_ready ? "done" : "none");
    let statusLine = "", badge = "";
    if (st === "done") {
      statusLine = readPct > 0 ? `${readPct}% lido` : "pronto para ouvir";
      badge = `<div class="book-badge">▶</div>`;
    } else if (st === "preparing") {
      statusLine = `preparando narração · ${pct}%`;
      badge = `<div class="book-loading"><div class="spinner"></div><span>${pct}%</span></div>`;
    } else if (st === "queued") {
      statusLine = a.position ? `na fila · ${a.position}º` : "na fila";
      badge = `<div class="book-badge queued">⏳</div>`;
    } else {
      statusLine = "áudio não preparado";
    }
    const card = document.createElement("div");
    card.className = "book " + (st === "done" ? "is-ready" : st === "none" ? "is-none" : "is-preparing");
    card.innerHTML = `
      <div class="book-cover">
        <div class="book-cover-fallback">📖</div>
        <img class="book-cover-img" src="/api/pdf/${it.job_id}/cover" alt=""
             onload="this.classList.add('loaded')" onerror="this.remove()">
        ${badge}
        ${it.source_warning ? `<div class="book-source-warn" title="${escapeHTML(it.source_warning)}">⚠</div>` : ""}
        ${readPct > 0 ? `<div class="book-progress"><div class="book-progress-fill" style="width:${readPct}%"></div></div>` : ""}
      </div>
      <div class="book-title" title="${escapeHTML(it.title || it.filename)}">${escapeHTML(it.title || it.filename)}</div>
      ${it.author ? `<div class="book-author">${escapeHTML(it.author)}</div>` : ""}
      <div class="book-meta">${it.pages || 0} págs${durStr ? " · " + durStr : ""}</div>
      <div class="book-sub">${statusLine}</div>
      ${snippet ? `<div class="book-snippet">“${escapeHTML(snippet)}”</div>` : ""}
      <div class="book-actions">
        ${st === "none" ? `<button class="book-act book-prepare" title="Preparar narração">🎧</button>` : ""}
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
    card.querySelector(".book-collection").addEventListener("click", (e) => { e.stopPropagation(); moveToCollection(it); });
    const prep = card.querySelector(".book-prepare");
    if (prep) prep.addEventListener("click", (e) => { e.stopPropagation(); prepareBook(it.job_id); });
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
      list = searchResults.map((r) => ({ item: allItems.find((x) => x.job_id === r.job_id), snippet: r.snippet })).filter((x) => x.item);
    } else {
      list = allItems.filter((x) => !activeCollection || x.collection === activeCollection).map((x) => ({ item: x, snippet: null }));
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
      allItems = (r.items || []).sort((a, b) => (b.last_opened || b.created_at || 0) - (a.last_opened || a.created_at || 0));
      const welcome = document.getElementById("view-welcome");
      if (welcome) welcome.classList.toggle("has-books", allItems.length > 0);
      if (!allItems.length) { lib.classList.add("hidden"); return; }
      lib.classList.remove("hidden");
      renderChips();
      applyFilter();
      const anyActive = allItems.some((it) => it.audio && (it.audio.status === "preparing" || it.audio.status === "queued"));
      const shelfVisible = !welcome.classList.contains("hidden");
      if (anyActive && shelfVisible && searchResults === null) shelfPoll = setTimeout(refreshLibrary, 2500);
    } catch { lib.classList.add("hidden"); }
  }

  // ---------- fila de narração ----------
  async function refreshQueue() {
    const btn = document.getElementById("btn-queue");
    const badge = document.getElementById("queue-badge");
    const list = document.getElementById("queue-list");
    if (!btn) return;
    try {
      const q = await window.LeIA.api.getJSON("/api/pdf/queue");
      const items = q.items || [];
      if (items.length) {
        btn.classList.remove("hidden");
        if (badge) { badge.textContent = String(items.length); badge.classList.remove("hidden"); }
      } else {
        btn.classList.add("hidden");
        if (badge) badge.classList.add("hidden");
      }
      if (list) {
        list.innerHTML = items.length ? "" : `<div class="bm-empty">Nada na fila.</div>`;
        items.forEach((it) => {
          const pct = it.total ? Math.round((it.done / it.total) * 100) : 0;
          const row = document.createElement("div");
          row.className = "queue-item";
          row.innerHTML = `<div class="queue-icon">${it.status === "preparing" ? `<div class="spinner"></div>` : "⏳"}</div>` +
            `<div class="queue-meta"><div class="queue-title">${escapeHTML(it.title)}</div>` +
            `<div class="queue-status">${it.status === "preparing" ? "preparando · " + pct + "%" : "na fila"}</div></div>`;
          list.appendChild(row);
        });
      }
      // continua atualizando enquanto houver atividade na fila
      if (queuePoll) { clearTimeout(queuePoll); queuePoll = null; }
      if (items.length) queuePoll = setTimeout(refreshQueue, 2000);
    } catch {}
  }

  document.addEventListener("DOMContentLoaded", () => {
    window.LeIA.toast = toast;
    window.LeIA.onBookAdded = onBookAdded;
    window.LeIA.openDoc = openDoc;
    window.LeIA.goHome = goHome;
    window.LeIA.refreshLibrary = refreshLibrary;
    window.LeIA.refreshQueue = refreshQueue;
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

    // popover da fila
    const qbtn = document.getElementById("btn-queue");
    const qpop = document.getElementById("queue-popover");
    if (qbtn && qpop) {
      qbtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = qpop.classList.toggle("open");
        if (open) {
          const rect = qbtn.getBoundingClientRect();
          qpop.style.left = `${Math.max(8, rect.right - 320)}px`;
          qpop.style.top = `${rect.bottom + 8}px`;
        }
      });
      document.addEventListener("click", (e) => { if (!qpop.contains(e.target) && e.target !== qbtn) qpop.classList.remove("open"); });
    }

    // Garante que o progresso vá pro disco ao fechar/minimizar a janela.
    window.addEventListener("pagehide", flushProgress);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") flushProgress();
    });

    showVersion();
    refreshHardwareBadge();
    refreshLibrary();
    refreshQueue();
  });
})();
