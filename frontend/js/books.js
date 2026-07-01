(function () {
  // Busca de livros grátis online (Gutenberg / Wikisource / Internet Archive).
  const SRC_KEY = "leia.bookSources";     // fontes ativas (filtro)
  const PREP_KEY = "leia.prepareOnAdd";    // mesmo toggle do upload

  let sources = [];          // [{id,label}]
  let enabled = null;         // Set de ids ativos
  let searchTimer = null;
  let lastQuery = "";

  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }

  function loadEnabled() {
    try {
      const raw = localStorage.getItem(SRC_KEY);
      if (raw) return new Set(JSON.parse(raw));
    } catch {}
    return new Set(sources.map((s) => s.id)); // todas por padrão
  }
  function saveEnabled() {
    try { localStorage.setItem(SRC_KEY, JSON.stringify([...enabled])); } catch {}
  }

  // ---------- abrir / fechar a tela de busca ----------
  function openExplore() {
    document.getElementById("view-welcome").classList.add("hidden");
    document.getElementById("view-processing").classList.add("hidden");
    document.getElementById("main-body").classList.add("hidden");
    document.getElementById("player-bar").classList.add("hidden");
    document.getElementById("view-explore").classList.remove("hidden");
    const inp = document.getElementById("explore-input");
    if (inp) setTimeout(() => inp.focus(), 30);
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

  // ---------- filtros de fonte ----------
  function renderSources() {
    const wrap = document.getElementById("explore-sources");
    if (!wrap) return;
    wrap.innerHTML = "";
    sources.forEach((s) => {
      const chip = document.createElement("button");
      chip.className = "src-chip" + (enabled.has(s.id) ? " active" : "");
      chip.innerHTML = `<span class="src-dot"></span>${esc(s.label)}`;
      chip.addEventListener("click", () => {
        if (enabled.has(s.id)) {
          if (enabled.size > 1) enabled.delete(s.id); // nunca zera tudo
        } else enabled.add(s.id);
        saveEnabled();
        renderSources();
        if (lastQuery) runSearch(lastQuery);
      });
      wrap.appendChild(chip);
    });
  }

  async function loadSources() {
    try {
      const r = await window.LeIA.api.getJSON("/api/books/sources");
      sources = r.sources || [];
    } catch { sources = []; }
    enabled = loadEnabled();
    renderSources();
  }

  // ---------- busca ----------
  function setStatus(html) {
    const el = document.getElementById("explore-status");
    if (el) el.innerHTML = html || "";
  }

  function runSearch(q) {
    lastQuery = q;
    const results = document.getElementById("explore-results");
    if (!q || q.length < 2) { setStatus(""); if (results) results.innerHTML = ""; return; }
    const srcs = [...enabled].join(",");
    setStatus(`<span class="ex-spin"></span> Buscando “${esc(q)}”…`);
    if (results) results.innerHTML = "";
    window.LeIA.api.getJSON(`/api/books/search?q=${encodeURIComponent(q)}&sources=${encodeURIComponent(srcs)}`)
      .then((r) => renderResults(r.groups || [], q))
      .catch(() => setStatus(`<span class="ex-warn">Não consegui buscar agora. Verifique a conexão e tente de novo.</span>`));
  }

  function debouncedSearch(q) {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(q), 350);
  }

  // ---------- resultados ----------
  function renderResults(groups, q) {
    const wrap = document.getElementById("explore-results");
    if (!wrap) return;
    wrap.innerHTML = "";
    if (!groups.length) {
      setStatus(`Nenhum resultado para “${esc(q)}” nas fontes selecionadas.`);
      return;
    }
    setStatus(`${groups.length} resultado${groups.length > 1 ? "s" : ""} para “${esc(q)}”.`);
    groups.forEach((g) => wrap.appendChild(resultCard(g)));
  }

  function resultCard(g) {
    // Estado local do cartão: qual fonte está selecionada.
    let selected = 0;
    const card = document.createElement("div");
    card.className = "ex-card";

    const cover = g.cover_url
      ? `<img class="ex-cover-img" src="${esc(g.cover_url)}" alt="" onload="this.classList.add('loaded')" onerror="this.remove()">`
      : "";

    card.innerHTML = `
      <div class="ex-cover"><div class="ex-cover-fallback">📖</div>${cover}</div>
      <div class="ex-info">
        <div class="ex-title" title="${esc(g.title)}">${esc(g.title)}</div>
        <div class="ex-author">${esc(g.author || "Autor desconhecido")}</div>
        <div class="ex-picker"></div>
        <div class="ex-warning-slot"></div>
        <div class="ex-foot">
          <button class="ex-add btn btn-primary">Adicionar à estante</button>
        </div>
      </div>`;

    const picker = card.querySelector(".ex-picker");
    const warnSlot = card.querySelector(".ex-warning-slot");
    const addBtn = card.querySelector(".ex-add");

    function renderWarning() {
      const src = g.sources[selected];
      warnSlot.innerHTML = src && src.warning
        ? `<div class="ex-warning">⚠ ${esc(src.warning)}</div>` : "";
    }

    if (g.sources.length > 1) {
      const label = document.createElement("span");
      label.className = "ex-picker-label";
      label.textContent = "Fonte:";
      picker.appendChild(label);
      g.sources.forEach((s, i) => {
        const b = document.createElement("button");
        b.className = "ex-src" + (i === selected ? " active" : "") + (s.warning ? " warn" : "");
        b.textContent = s.label;
        b.addEventListener("click", () => {
          selected = i;
          picker.querySelectorAll(".ex-src").forEach((x, j) => x.classList.toggle("active", j === i));
          renderWarning();
        });
        picker.appendChild(b);
      });
    } else {
      picker.innerHTML = `<span class="ex-src-single">${esc(g.sources[0].label)}</span>`;
    }
    renderWarning();

    addBtn.addEventListener("click", () => importGroup(g, () => g.sources[selected], addBtn));
    return card;
  }

  // ---------- importar (baixar → estante) ----------
  async function importGroup(group, getSource, btn) {
    const src = getSource();
    const prepEl = document.getElementById("explore-prepare");
    const prepare = !!(prepEl && prepEl.checked);
    btn.disabled = true;
    btn.classList.add("loading");
    btn.innerHTML = `<span class="ex-spin"></span> Baixando…`;
    try {
      const { job_id } = await window.LeIA.api.postJSON("/api/books/import", {
        source: src.source,
        id: src.id,
        title: group.title,
        author: group.author,
        download_url: src.download_url,
        ext: src.ext,
        warning: src.warning,
        prepare,
      });
      await window.LeIA.api.pollJob(job_id, (s) => {
        const pct = Math.round((s.progress || 0) * 100);
        btn.innerHTML = `<span class="ex-spin"></span> ${s.status === "queued" ? "Baixando…" : "Processando… " + pct + "%"}`;
      }, 700);
      btn.classList.remove("loading");
      btn.classList.add("done");
      btn.innerHTML = "✓ Na estante";
      window.LeIA.toast(`📚 “${group.title}” foi para a estante.`, "success");
      if (window.LeIA.refreshLibrary) window.LeIA.refreshLibrary();
      if (window.LeIA.refreshQueue) window.LeIA.refreshQueue();
    } catch (e) {
      btn.disabled = false;
      btn.classList.remove("loading");
      btn.innerHTML = "Tentar de novo";
      window.LeIA.toast("Falha ao adicionar: " + (e.message || e), "danger");
    }
  }

  function init() {
    loadSources();

    const prepEl = document.getElementById("explore-prepare");
    if (prepEl) {
      prepEl.checked = localStorage.getItem(PREP_KEY) === "1";
      prepEl.addEventListener("change", () => {
        try { localStorage.setItem(PREP_KEY, prepEl.checked ? "1" : "0"); } catch {}
      });
    }

    const input = document.getElementById("explore-input");
    if (input) {
      input.addEventListener("input", () => debouncedSearch(input.value.trim()));
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(input.value.trim()); });
    }
    const go = document.getElementById("explore-go");
    if (go && input) go.addEventListener("click", () => runSearch(input.value.trim()));

    const btnTop = document.getElementById("btn-explore");
    if (btnTop) btnTop.addEventListener("click", openExplore);
    const btnWelcome = document.getElementById("btn-explore-welcome");
    if (btnWelcome) btnWelcome.addEventListener("click", openExplore);
    const back = document.getElementById("explore-back");
    if (back) back.addEventListener("click", closeExplore);
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.openExplore = openExplore;
  window.LeIA.closeExplore = closeExplore;
  window.LeIA.exploreIsOpen = isOpen;
  document.addEventListener("DOMContentLoaded", init);
})();
