(function () {
  const AUTOPLAY_KEY = "leia.autoplay";
  const CFG_KEY = "leia.cleaning";

  const FONT_STACKS = {
    serif: "var(--font-reader)",
    sans: "var(--font-ui)",
    dyslexic: "'OpenDyslexic', var(--font-ui)",
  };

  function setVar(name, val) { document.documentElement.style.setProperty(name, val); }

  // ---- aplicadores de aparência ----
  function applyFont(key) { setVar("--reader-font", FONT_STACKS[key] || FONT_STACKS.serif); }
  function applyWeight(w) { setVar("--reader-weight", w || "400"); }
  function applyLineHeight(lh) { setVar("--reader-lineheight", lh || "1.75"); }
  function applyMargin(mw) { setVar("--reader-maxwidth", (mw || "1000") + "px"); }
  function applyWarm(v) {
    const o = document.getElementById("warm-overlay");
    if (o) o.style.opacity = String(((parseInt(v, 10) || 0) / 100) * 0.4);
  }
  function applyBright(v) {
    const o = document.getElementById("dim-overlay");
    const b = parseInt(v, 10);
    if (o && !isNaN(b)) o.style.opacity = String(((100 - b) / 100) * 0.7);
  }

  // ---- controles genéricos ----
  function bindSeg(id, dataKey, apply, storeKey) {
    const cont = document.getElementById(id);
    if (!cont) return;
    cont.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        cont.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
        apply(btn.dataset[dataKey]);
        try { localStorage.setItem(storeKey, btn.dataset[dataKey]); } catch {}
      });
    });
  }
  function setSegActive(id, dataKey, val) {
    const cont = document.getElementById(id);
    if (!cont || val == null) return;
    cont.querySelectorAll(".seg-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset[dataKey] === String(val))
    );
  }
  function bindSlider(id, apply, storeKey) {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", () => {
      apply(el.value);
      try { localStorage.setItem(storeKey, el.value); } catch {}
    });
  }

  // Aplica tudo que está salvo (chamado na carga, antes de abrir o modal).
  function applyAppearance() {
    try {
      const size = parseInt(localStorage.getItem("leia.reader.size") || "19", 10);
      window.LeIA.reader.setReaderFontSize(size);
      setSegActive("size-presets", "size", size);

      const font = localStorage.getItem("leia.font") || "serif";
      applyFont(font); setSegActive("font-presets", "font", font);

      const weight = localStorage.getItem("leia.weight") || "400";
      applyWeight(weight); setSegActive("weight-presets", "weight", weight);

      const lh = localStorage.getItem("leia.lh") || "1.75";
      applyLineHeight(lh); setSegActive("spacing-presets", "lh", lh);

      const mw = localStorage.getItem("leia.mw") || "1000";
      applyMargin(mw); setSegActive("margin-presets", "mw", mw);

      const warm = localStorage.getItem("leia.warm") || "0";
      applyWarm(warm);
      const ws = document.getElementById("warm-slider"); if (ws) ws.value = warm;

      const bright = localStorage.getItem("leia.bright") || "100";
      applyBright(bright);
      const bs = document.getElementById("bright-slider"); if (bs) bs.value = bright;

      const autoplay = localStorage.getItem(AUTOPLAY_KEY) === "1";
      const ap = document.getElementById("toggle-autoplay");
      if (ap) ap.classList.toggle("on", autoplay);

      const th = document.getElementById("toggle-theme");
      if (th) th.classList.toggle("on", localStorage.getItem("leia.theme") === "light");
    } catch {}
  }

  function open() {
    document.getElementById("settings-backdrop").classList.add("open");
    refreshSystemInfo();
    renderStats();
  }
  function close() { document.getElementById("settings-backdrop").classList.remove("open"); }

  function fmtMin(sec) {
    const m = Math.round(sec / 60);
    if (m < 60) return m + " min";
    const h = Math.floor(m / 60), mm = m % 60;
    return mm ? `${h} h ${mm} min` : `${h} h`;
  }
  function renderStats() {
    const wrap = document.getElementById("stats-info");
    if (!wrap || !window.LeIA.stats) return;
    const s = window.LeIA.stats.summary();
    const goalSec = s.goalMin * 60;
    const todayPct = goalSec ? Math.min(100, Math.round((s.todaySec / goalSec) * 100)) : 0;
    const maxBar = Math.max(60, ...s.last7.map((d) => d.sec));
    const bars = s.last7.map((d) =>
      `<div class="stat-bar" title="${fmtMin(d.sec)}"><div class="stat-bar-fill" style="height:${Math.round((d.sec / maxBar) * 100)}%"></div><span>${d.label}</span></div>`
    ).join("");
    wrap.innerHTML = `
      <div class="stats-cards">
        <div class="stat-card"><div class="stat-num">🔥 ${s.streak}</div><div class="stat-lbl">dias seguidos</div></div>
        <div class="stat-card"><div class="stat-num">${fmtMin(s.total)}</div><div class="stat-lbl">tempo total</div></div>
        <div class="stat-card"><div class="stat-num">${s.daysActive}</div><div class="stat-lbl">dias de leitura</div></div>
      </div>
      <div class="modal-row"><div class="modal-row-label">Hoje</div><div>${fmtMin(s.todaySec)} / ${s.goalMin} min · ${todayPct}%</div></div>
      <div class="goal-track"><div class="goal-fill" style="width:${todayPct}%"></div></div>
      <div class="stats-chart">${bars}</div>
    `;
    const gp = document.getElementById("goal-presets");
    if (gp) gp.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", parseInt(b.dataset.goal, 10) === s.goalMin));
  }

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

    // Aparência
    bindSeg("size-presets", "size", (v) => window.LeIA.reader.setReaderFontSize(parseInt(v, 10)), "leia.reader.size");
    bindSeg("font-presets", "font", applyFont, "leia.font");
    bindSeg("weight-presets", "weight", applyWeight, "leia.weight");
    bindSeg("spacing-presets", "lh", applyLineHeight, "leia.lh");
    bindSeg("margin-presets", "mw", applyMargin, "leia.mw");
    bindSlider("warm-slider", applyWarm, "leia.warm");
    bindSlider("bright-slider", applyBright, "leia.bright");

    // Estatísticas: meta diária
    const gp = document.getElementById("goal-presets");
    if (gp) gp.querySelectorAll(".seg-btn").forEach((b) => b.addEventListener("click", () => {
      if (window.LeIA.stats) window.LeIA.stats.setGoalMin(parseInt(b.dataset.goal, 10));
      renderStats();
    }));

    // Limpeza
    document.querySelectorAll(".switch[data-cfg]").forEach((sw) => {
      const key = `${CFG_KEY}.${sw.dataset.cfg}`;
      const stored = localStorage.getItem(key);
      if (stored !== null) sw.classList.toggle("on", stored === "1");
      sw.addEventListener("click", () => {
        sw.classList.toggle("on");
        try { localStorage.setItem(key, sw.classList.contains("on") ? "1" : "0"); } catch {}
      });
    });

    // Leitura
    const ap = document.getElementById("toggle-autoplay");
    if (ap) {
      ap.addEventListener("click", () => {
        ap.classList.toggle("on");
        try { localStorage.setItem(AUTOPLAY_KEY, ap.classList.contains("on") ? "1" : "0"); } catch {}
      });
    }

    // Tema
    const th = document.getElementById("toggle-theme");
    if (th) {
      th.addEventListener("click", () => {
        const light = !th.classList.contains("on");
        th.classList.toggle("on", light);
        document.documentElement.setAttribute("data-theme", light ? "light" : "dark");
        try { localStorage.setItem("leia.theme", light ? "light" : "dark"); } catch {}
      });
    }

    window.LeIA.shortcuts.on("Escape", close);
    applyAppearance();
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.settings = { initSettings, open, close };
})();
