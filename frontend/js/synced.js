// Reprodução SINCRONIZADA: toca um áudio (audiolivro humano) que o usuário
// importou e destaca a frase do texto conforme os tempos do alinhamento.
// Quando ativo, "assume" os controles do player (play, próx/ant, scrubber).
(function () {
  const S = {
    active: false, audio: null, map: [], byId: new Map(),
    jobId: null, curId: null,
  };

  const $ = (id) => document.getElementById(id);
  const pl = () => window.LeIA.player;

  function isActive() { return S.active; }

  function unload() {
    if (S.audio) { try { S.audio.pause(); } catch {} S.audio = null; }
    S.active = false; S.map = []; S.byId = new Map(); S.jobId = null; S.curId = null;
  }

  async function load(jobId) {
    unload();
    try {
      const st = await window.LeIA.api.getJSON(`/api/pdf/${jobId}/sync-status`);
      if (!st || st.status !== "done") return false;
      const al = await window.LeIA.api.getJSON(`/api/pdf/${jobId}/alignment`);
      const sents = (al.sentences || []).filter((x) => x && x.id && window.LeIA.reader.state.sentenceById.has(x.id));
      if (!sents.length) return false;
      S.map = sents.slice().sort((a, b) => a.start - b.start);
      S.byId = new Map(sents.map((x) => [x.id, x]));
      S.jobId = jobId;
      S.audio = new Audio(`/api/pdf/${jobId}/synced-audio`);
      S.audio.preload = "auto";
      S.audio.volume = pl().state.muted ? 0 : pl().state.volume;
      S.audio.playbackRate = pl().state.speed || 1;
      S.audio.addEventListener("ended", pause);
      S.audio.addEventListener("timeupdate", tick);  // dirige o destaque + scrubber
      S.active = true;
      pl().setReady(true);                 // libera o play (não depende da IA)
      // posiciona o áudio na frase atual (retomada)
      const cur = pl().state.currentSentenceId;
      if (cur && S.byId.has(cur)) S.audio.currentTime = S.byId.get(cur).start + 0.01;
      updateScrubber();
      return true;
    } catch {
      return false;
    }
  }

  function findAt(t) {
    let lo = 0, hi = S.map.length - 1, res = S.map[0];
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (S.map[mid].start <= t) { res = S.map[mid]; lo = mid + 1; } else hi = mid - 1;
    }
    return res;
  }

  function tick() {
    if (!S.audio) return;
    const s = findAt(S.audio.currentTime);
    if (s && s.id !== S.curId) {
      S.curId = s.id;
      window.LeIA.reader.highlight(s.id);
      pl().state.currentSentenceId = s.id;
      updateProgress();
      const rs = window.LeIA.reader.state.sentenceById.get(s.id);
      if (rs && window.LeIA.saveProgress) window.LeIA.saveProgress(rs.globalIndex);
    }
    updateScrubber();
  }

  function play() {
    if (!S.audio) return;
    S.audio.play().then(() => {
      pl().state.isPlaying = true;
      setIcon("pause");
    }).catch(() => {
      pl().state.isPlaying = false;
      setIcon("play");
    });
  }
  function pause() {
    if (S.audio) S.audio.pause();
    pl().state.isPlaying = false;
    setIcon("play");
  }
  function toggle() { if (S.audio) (S.audio.paused ? play() : pause()); }

  function seekToId(sid) {
    const s = S.byId.get(sid);
    if (!s || !S.audio) return;
    S.audio.currentTime = s.start + 0.01;
    S.curId = sid;
    window.LeIA.reader.highlight(sid);
    pl().state.currentSentenceId = sid;
    updateProgress(); updateScrubber();
  }
  function step(delta) {
    const cur = pl().state.currentSentenceId;
    let idx = S.map.findIndex((x) => x.id === cur);
    idx = Math.max(0, Math.min(S.map.length - 1, (idx < 0 ? 0 : idx) + delta));
    seekToId(S.map[idx].id);
  }
  function seekRatio(r) {
    if (!S.audio || !isFinite(S.audio.duration)) return;
    S.audio.currentTime = Math.max(0, Math.min(1, r)) * S.audio.duration;
    const s = findAt(S.audio.currentTime);
    if (s) { S.curId = s.id; window.LeIA.reader.highlight(s.id); pl().state.currentSentenceId = s.id; }
    updateProgress(); updateScrubber();
  }
  function setSpeed(v) { if (S.audio) S.audio.playbackRate = v; }
  function setVolume(v, muted) { if (S.audio) S.audio.volume = muted ? 0 : v; }

  // ---- UI (reusa os elementos do player) ----
  function setIcon(kind) {
    ["icon-play", "icon-pause", "icon-loading"].forEach((id) => $(id) && $(id).classList.add("hidden"));
    if (kind === "play" && $("icon-play")) $("icon-play").classList.remove("hidden");
    if (kind === "pause" && $("icon-pause")) $("icon-pause").classList.remove("hidden");
    const b = $("btn-play"); if (b) b.classList.toggle("playing", kind === "pause");
  }
  function updateProgress() {
    const r = window.LeIA.reader.state;
    const s = r.sentenceById.get(pl().state.currentSentenceId);
    if (!s) return;
    const pt = $("player-time");
    if (pt) pt.textContent = `${Math.round((s.globalIndex / r.sentences.length) * 100)}% · ${s.globalIndex + 1}/${r.sentences.length}`;
  }
  function updateScrubber() {
    if (!S.audio || !isFinite(S.audio.duration) || !S.audio.duration) return;
    const pct = (S.audio.currentTime / S.audio.duration) * 100;
    if ($("scrubber-fill")) $("scrubber-fill").style.width = pct + "%";
    if ($("scrubber-buffer")) $("scrubber-buffer").style.width = "100%";
    if ($("scrubber-thumb")) $("scrubber-thumb").style.left = pct + "%";
    const tl = $("time-left");
    if (tl) {
      const rem = Math.max(0, S.audio.duration - S.audio.currentTime);
      const m = Math.floor(rem / 60), s = Math.round(rem % 60);
      tl.textContent = `voz humana · ${m}:${String(s).padStart(2, "0")} restantes`;
    }
  }

  // ---- Importar áudio ----
  function setStatus(txt) {
    const el = $("prep-status");
    if (!el) return;
    if (txt) { el.textContent = txt; el.className = "prep-status preparing"; el.classList.remove("hidden"); }
    else { el.classList.add("hidden"); }
  }

  async function importFile(file) {
    const jid = window.LeIA.currentJobId;
    if (!jid) return;
    setStatus("Enviando áudio…");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const resp = await fetch(`/api/pdf/${jid}/import-audio`, { method: "POST", body: fd });
      if (!resp.ok) throw new Error(await resp.text());
      window.LeIA.toast("🎧 Sincronizando o áudio com o texto… pode levar alguns minutos.", "info");
      pollSync(jid);
    } catch (e) {
      setStatus("");
      window.LeIA.toast("Falha ao importar: " + (e.message || e), "danger");
    }
  }

  function pollSync(jid) {
    window.LeIA.api.getJSON(`/api/pdf/${jid}/sync-status`).then((s) => {
      if (jid !== window.LeIA.currentJobId) return;   // trocou de livro
      if (s.status === "transcribing" || s.status === "aligning") {
        setStatus(`Sincronizando… ${Math.round((s.progress || 0) * 100)}%`);
        setTimeout(() => pollSync(jid), 1500);
      } else if (s.status === "done") {
        setStatus("");
        window.LeIA.toast("✅ Áudio sincronizado! Toque em play para ouvir a voz humana.", "success");
        load(jid);
      } else if (s.status === "error") {
        setStatus("");
        window.LeIA.toast("Erro ao sincronizar: " + (s.error || "desconhecido"), "danger");
      } else {
        setTimeout(() => pollSync(jid), 1500);
      }
    }).catch(() => setTimeout(() => pollSync(jid), 2000));
  }

  function init() {
    const btn = $("btn-import-audio");
    const input = $("import-audio-input");
    if (btn && input) {
      btn.addEventListener("click", () => input.click());
      input.addEventListener("change", () => {
        if (input.files && input.files[0]) importFile(input.files[0]);
        input.value = "";
      });
    }
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.synced = { init, load, unload, isActive, toggle, play, pause, seekToId, step, seekRatio, setSpeed, setVolume };
})();
