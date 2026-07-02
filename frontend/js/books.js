(function () {
  // Descoberta de livros grátis (Gutenberg / Wikisource / Internet Archive):
  // vitrine de populares + gêneros (estilo Kindle) e busca por título/autor.
  const SRC_KEY = "leia.bookSources";     // fontes ativas (filtro da busca)
  const PREP_KEY = "leia.prepareOnAdd";    // mesmo toggle do upload

  let sources = [];          // [{id,label}]
  let enabled = null;         // Set de ids ativos (busca)
  let genres = [];            // [{id,label}]
  let mode = "browse";        // "browse" | "search"
  let currentGenre = "";      // "" = populares
  let page = 1, hasMore = false, loading = false;
  let searchTimer = null, lastQuery = "";
  let detailGroup = null, detailSource = 0;

  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }
  function fmtNum(n) { try { return Number(n || 0).toLocaleString("pt-BR"); } catch { return String(n || 0); } }

  // ---------- filtro de fontes (usado na busca) ----------
  function loadEnabled() {
    try { const raw = localStorage.getItem(SRC_KEY); if (raw) return new Set(JSON.parse(raw)); } catch {}
    return new Set(sources.map((s) => s.id));
  }
  function saveEnabled() { try { localStorage.setItem(SRC_KEY, JSON.stringify([...enabled])); } catch {} }

  function renderSources() {
    const wrap = document.getElementById("explore-sources");
    if (!wrap) return;
    wrap.innerHTML = "";
    sources.forEach((s) => {
      const chip = document.createElement("button");
      chip.className = "src-chip" + (enabled.has(s.id) ? " active" : "");
      chip.innerHTML = `<span class="src-dot"></span>${esc(s.label)}`;
      chip.addEventListener("click", () => {
        if (enabled.has(s.id)) { if (enabled.size > 1) enabled.delete(s.id); }
        else enabled.add(s.id);
        saveEnabled(); renderSources();
        if (lastQuery) runSearch(lastQuery);
      });
      wrap.appendChild(chip);
    });
  }
  async function loadSources() {
    try { sources = (await window.LeIA.api.getJSON("/api/books/sources")).sources || []; }
    catch { sources = []; }
    enabled = loadEnabled();
    renderSources();
  }

  // ---------- gêneros (vitrine) ----------
  async function loadGenres() {
    try { genres = (await window.LeIA.api.getJSON("/api/books/genres")).genres || []; }
    catch { genres = []; }
    renderGenres();
  }
  function renderGenres() {
    const wrap = document.getElementById("explore-genres");
    if (!wrap) return;
    wrap.innerHTML = "";
    const mk = (id, label) => {
      const c = document.createElement("button");
      c.className = "genre-chip" + (mode === "browse" && currentGenre === id ? " active" : "");
      c.textContent = label;
      c.addEventListener("click", () => {
        const inp = document.getElementById("explore-input"); if (inp) inp.value = "";
        currentGenre = id;
        loadBrowse(id, 1, false);
      });
      return c;
    };
    wrap.appendChild(mk("", "🔥 Populares"));
    genres.forEach((g) => wrap.appendChild(mk(g.id, g.label)));
  }

  // ---------- abrir / fechar a tela ----------
  function openExplore() {
    document.getElementById("view-welcome").classList.add("hidden");
    document.getElementById("view-processing").classList.add("hidden");
    document.getElementById("main-body").classList.add("hidden");
    document.getElementById("player-bar").classList.add("hidden");
    document.getElementById("view-explore").classList.remove("hidden");
    if (!document.querySelector("#explore-results .bk-card")) loadBrowse(currentGenre, 1, false);
  }
  function closeExplore() {
    document.getElementById("view-explore").classList.add("hidden");
    document.getElementById("view-welcome").classList.remove("hidden");
    if (window.LeIA.refreshLibrary) window.LeIA.refreshLibrary();
  }
  function isOpen() {
    const v = document.getElementById("view-explore");
    return v && !v.classList.contains("hidden");
  }

  function setStatus(html) { const el = document.getElementById("explore-status"); if (el) el.innerHTML = html || ""; }
  function showControls(show) {
    const c = document.querySelector(".explore-controls");
    if (c) c.classList.toggle("hidden", !show);
  }
  function setMore(show) {
    const b = document.getElementById("explore-more");
    if (b) b.classList.toggle("hidden", !show);
  }

  // ---------- vitrine (browse) ----------
  async function loadBrowse(genre, pg, append) {
    if (loading) return;
    loading = true;
    mode = "browse"; currentGenre = genre || ""; page = pg || 1;
    showControls(false);
    renderGenres();
    if (!append) { document.getElementById("explore-results").innerHTML = ""; setMore(false); }
    setStatus(`<span class="ex-spin"></span> Carregando…`);
    try {
      const r = await window.LeIA.api.getJSON(`/api/books/browse?genre=${encodeURIComponent(currentGenre)}&page=${page}`);
      const groups = r.groups || [];
      hasMore = !!r.has_more;
      renderGrid(groups, append);
      const label = currentGenre ? (genres.find((g) => g.id === currentGenre) || {}).label : "Populares";
      setStatus(groups.length || append ? `${esc(label || "Populares")} · em português` : `Nada encontrado em “${esc(label)}”.`);
      setMore(hasMore);
    } catch {
      setStatus(`<span class="ex-warn">Não consegui carregar agora. Verifique a conexão.</span>`);
    } finally { loading = false; }
  }

  // ---------- busca ----------
  function runSearch(q) {
    lastQuery = q; mode = "search";
    const results = document.getElementById("explore-results");
    if (!q || q.length < 2) { setStatus(""); if (results) results.innerHTML = ""; setMore(false); showControls(false); loadBrowse(currentGenre, 1, false); return; }
    showControls(true);
    renderGenres();
    setMore(false);
    const srcs = [...enabled].join(",");
    setStatus(`<span class="ex-spin"></span> Buscando “${esc(q)}”…`);
    if (results) results.innerHTML = "";
    window.LeIA.api.getJSON(`/api/books/search?q=${encodeURIComponent(q)}&sources=${encodeURIComponent(srcs)}`)
      .then((r) => {
        const groups = r.groups || [];
        renderGrid(groups, false);
        setStatus(groups.length ? `${groups.length} resultado${groups.length > 1 ? "s" : ""} para “${esc(q)}”.` : `Nenhum resultado para “${esc(q)}”.`);
      })
      .catch(() => setStatus(`<span class="ex-warn">Não consegui buscar agora.</span>`));
  }
  function debouncedSearch(q) {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(q), 350);
  }

  // ---------- grade de capas ----------
  function renderGrid(groups, append) {
    const wrap = document.getElementById("explore-results");
    if (!wrap) return;
    if (!append) wrap.innerHTML = "";
    groups.forEach((g) => wrap.appendChild(coverCard(g)));
  }
  function coverCard(g) {
    const card = document.createElement("div");
    card.className = "bk-card";
    const cover = g.cover_url
      ? `<img class="bk-cover-img" src="${esc(g.cover_url)}" alt="" loading="lazy" onload="this.classList.add('loaded')" onerror="this.remove()">`
      : "";
    const warn = g.warning ? `<div class="bk-warn" title="${esc(g.warning)}">⚠</div>` : "";
    const dl = g.downloads ? `<div class="bk-dl" title="Downloads no Project Gutenberg">↓ ${fmtNum(g.downloads)}</div>` : "";
    card.innerHTML = `
      <div class="bk-cover">
        <div class="bk-cover-fallback">📖</div>
        ${cover}${warn}${dl}
      </div>
      <div class="bk-title" title="${esc(g.title)}">${esc(g.title)}</div>
      <div class="bk-author">${esc(g.author || "Autor desconhecido")}</div>`;
    card.addEventListener("click", () => openDetail(g));
    return card;
  }

  // ---------- modal de detalhe ----------
  function openDetail(g) {
    detailGroup = g; detailSource = 0;
    const $ = (id) => document.getElementById(id);
    $("bd-title").textContent = g.title || "";
    $("bd-author").textContent = g.author || "Autor desconhecido";
    const bits = [];
    if (g.downloads) bits.push(`↓ ${fmtNum(g.downloads)} downloads`);
    bits.push("Português");
    $("bd-meta").textContent = bits.join(" · ");
    // capa
    const img = $("bd-cover-img");
    if (g.cover_url) { img.src = g.cover_url; img.style.display = ""; } else { img.removeAttribute("src"); img.style.display = "none"; }
    // assuntos/gêneros
    const subj = $("bd-subjects");
    subj.innerHTML = "";
    (g.subjects || []).slice(0, 6).forEach((s) => {
      const t = document.createElement("span"); t.className = "bd-tag"; t.textContent = s; subj.appendChild(t);
    });
    // sinopse
    $("bd-summary").textContent = g.summary || "";
    $("bd-summary").classList.toggle("hidden", !g.summary);
    // fonte(s)
    renderDetailSource();
    // preparar (default = preferência global)
    const prep = $("bd-prepare");
    if (prep) prep.checked = localStorage.getItem(PREP_KEY) === "1";
    // botão
    const add = $("bd-add");
    add.disabled = false; add.className = "btn btn-primary bd-add"; add.textContent = "Adicionar à estante";
    document.getElementById("book-modal-backdrop").classList.add("open");
  }
  function renderDetailSource() {
    const g = detailGroup, wrap = document.getElementById("bd-source"), warnEl = document.getElementById("bd-warning");
    wrap.innerHTML = "";
    if (g.sources.length > 1) {
      const lbl = document.createElement("span"); lbl.className = "bd-src-label"; lbl.textContent = "Fonte:"; wrap.appendChild(lbl);
      g.sources.forEach((s, i) => {
        const b = document.createElement("button");
        b.className = "ex-src" + (i === detailSource ? " active" : "") + (s.warning ? " warn" : "");
        b.textContent = s.label;
        b.addEventListener("click", () => { detailSource = i; renderDetailSource(); });
        wrap.appendChild(b);
      });
    } else {
      wrap.innerHTML = `<span class="bd-src-single">${esc(g.sources[0].label)}</span>`;
    }
    const src = g.sources[detailSource];
    warnEl.textContent = src && src.warning ? "⚠ " + src.warning : "";
    warnEl.classList.toggle("hidden", !(src && src.warning));
  }
  function closeDetail() { document.getElementById("book-modal-backdrop").classList.remove("open"); }

  async function addFromDetail() {
    const g = detailGroup, src = g.sources[detailSource];
    const prepare = !!document.getElementById("bd-prepare").checked;
    const btn = document.getElementById("bd-add");
    btn.disabled = true; btn.classList.add("loading"); btn.innerHTML = `<span class="ex-spin"></span> Baixando…`;
    try {
      const { job_id } = await window.LeIA.api.postJSON("/api/books/import", {
        source: src.source, id: src.id, title: g.title, author: g.author,
        download_url: src.download_url, ext: src.ext, warning: src.warning, prepare,
      });
      await window.LeIA.api.pollJob(job_id, (s) => {
        const pct = Math.round((s.progress || 0) * 100);
        btn.innerHTML = `<span class="ex-spin"></span> ${s.status === "queued" ? "Baixando…" : "Processando… " + pct + "%"}`;
      }, 700);
      btn.classList.remove("loading"); btn.classList.add("done"); btn.innerHTML = "✓ Na estante";
      window.LeIA.toast(`📚 “${g.title}” foi para a estante.`, "success");
      if (window.LeIA.refreshLibrary) window.LeIA.refreshLibrary();
      if (window.LeIA.refreshQueue) window.LeIA.refreshQueue();
      setTimeout(closeDetail, 900);
    } catch (e) {
      btn.disabled = false; btn.classList.remove("loading"); btn.innerHTML = "Tentar de novo";
      window.LeIA.toast("Falha ao adicionar: " + (e.message || e), "danger");
    }
  }

  function init() {
    loadSources();
    loadGenres();

    const input = document.getElementById("explore-input");
    if (input) {
      input.addEventListener("input", () => debouncedSearch(input.value.trim()));
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(input.value.trim()); });
    }
    const go = document.getElementById("explore-go");
    if (go && input) go.addEventListener("click", () => runSearch(input.value.trim()));

    const more = document.getElementById("explore-more");
    if (more) more.addEventListener("click", () => { if (mode === "browse") loadBrowse(currentGenre, page + 1, true); });

    const btnTop = document.getElementById("btn-explore");
    if (btnTop) btnTop.addEventListener("click", openExplore);
    const btnWelcome = document.getElementById("btn-explore-welcome");
    if (btnWelcome) btnWelcome.addEventListener("click", openExplore);
    const back = document.getElementById("explore-back");
    if (back) back.addEventListener("click", closeExplore);

    // modal
    document.getElementById("bd-add").addEventListener("click", addFromDetail);
    document.getElementById("book-modal-close").addEventListener("click", closeDetail);
    document.getElementById("book-modal-backdrop").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeDetail();
    });
    const prep = document.getElementById("bd-prepare");
    if (prep) prep.addEventListener("change", () => { try { localStorage.setItem(PREP_KEY, prep.checked ? "1" : "0"); } catch {} });

    showControls(false); // sources só aparecem na busca
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.openExplore = openExplore;
  window.LeIA.closeExplore = closeExplore;
  window.LeIA.exploreIsOpen = isOpen;
  document.addEventListener("DOMContentLoaded", init);
})();
