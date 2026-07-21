// Reprodução SINCRONIZADA: toca um áudio (audiolivro humano) que o usuário
// importou e destaca a frase do texto conforme os tempos do alinhamento.
// Também gerencia a FONTE de áudio do livro (voz IA x áudio humano), a
// sincronização em segundo plano e a troca fácil entre as duas.
(function () {
  const S = {
    active: false, audio: null, map: [], byId: new Map(),
    jobId: null, curId: null,
    status: { has: false, syncing: false, incomplete: false, pct: 0 },
  };

  const $ = (id) => document.getElementById(id);
  const pl = () => window.LeIA.player;
  const api = () => window.LeIA.api;

  function isActive() { return S.active; }
  function getStatus() { return S.status; }

  // preferência de fonte por livro: "human" | "ai"
  const prefKey = (jid) => "leia.audioSource." + jid;
  const getPref = (jid) => { try { return localStorage.getItem(prefKey(jid)); } catch { return null; } };
  const setPref = (jid, v) => { try { localStorage.setItem(prefKey(jid), v); } catch {} };

  // ---------------------------------------------------------------- playback
  function unload() {
    if (S.audio) { try { S.audio.pause(); } catch {} S.audio = null; }
    S.active = false; S.map = []; S.byId = new Map(); S.curId = null;
  }

  async function load(jobId) {
    unload();
    try {
      const al = await api().getJSON(`/api/pdf/${jobId}/alignment`);
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
      S.audio.addEventListener("timeupdate", tick);
      S.active = true;
      pl().setReady(true);
      const cur = pl().state.currentSentenceId;
      if (cur && S.byId.has(cur)) S.audio.currentTime = S.byId.get(cur).start + 0.01;
      updateVoiceLabel();
      updateScrubber();
      return true;
    } catch {
      return false;
    }
  }

  function findAt(t) {
    let lo = 0, hi = S.map.length - 1, res = S.map[0];
    while (lo <= hi) { const m = (lo + hi) >> 1; if (S.map[m].start <= t) { res = S.map[m]; lo = m + 1; } else hi = m - 1; }
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
    S.audio.play().then(() => { pl().state.isPlaying = true; setIcon("pause"); })
      .catch(() => { pl().state.isPlaying = false; setIcon("play"); });
  }
  function pause() { if (S.audio) S.audio.pause(); pl().state.isPlaying = false; setIcon("play"); }
  function toggle() { if (S.audio) (S.audio.paused ? play() : pause()); }

  function seekToId(sid) {
    const s = S.byId.get(sid);
    if (!s || !S.audio) return;
    S.audio.currentTime = s.start + 0.01;
    S.curId = sid; window.LeIA.reader.highlight(sid); pl().state.currentSentenceId = sid;
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

  // ---------------------------------------------------------------- UI helpers
  function setIcon(kind) {
    ["icon-play", "icon-pause", "icon-loading"].forEach((id) => $(id) && $(id).classList.add("hidden"));
    if (kind === "play" && $("icon-play")) $("icon-play").classList.remove("hidden");
    if (kind === "pause" && $("icon-pause")) $("icon-pause").classList.remove("hidden");
    const b = $("btn-play"); if (b) b.classList.toggle("playing", kind === "pause");
  }
  function updateVoiceLabel() {
    const el = $("voice-label");
    if (el && S.active) el.textContent = "Voz humana";
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
      tl.textContent = `voz humana · ${Math.floor(rem / 60)}:${String(Math.round(rem % 60)).padStart(2, "0")} restantes`;
    }
  }
  function setStatus(txt) {
    const el = $("prep-status");
    if (!el) return;
    if (txt) { el.textContent = txt; el.className = "prep-status preparing"; el.classList.remove("hidden"); }
    else el.classList.add("hidden");
  }

  // ---------------------------------------------------------------- gerência
  async function refreshStatus(jobId) {
    try {
      const st = await api().getJSON(`/api/pdf/${jobId}/sync-status`);
      if (st.status === "done") S.status = { has: true, syncing: false, incomplete: false, pct: 100 };
      else if (st.status === "transcribing" || st.status === "aligning") S.status = { has: false, syncing: true, incomplete: false, pct: Math.round((st.progress || 0) * 100) };
      else if (st.status === "incomplete") S.status = { has: false, syncing: false, incomplete: true, pct: 0 };
      else S.status = { has: false, syncing: false, incomplete: false, pct: 0 };
    } catch { S.status = { has: false, syncing: false, incomplete: false, pct: 0 }; }
    return S.status;
  }

  // chamado ao ABRIR um livro → decide o modo (humano x IA) e religa o progresso
  async function onOpen(jobId) {
    const st = await refreshStatus(jobId);
    if (st.has && getPref(jobId) !== "ai") { await load(jobId); return true; }
    if (st.syncing) { setStatus(`Sincronizando o áudio… ${st.pct}%`); pollSync(jobId); }
    else if (st.incomplete) { resync(jobId); }   // app fechou no meio → retoma sozinho
    return false;
  }

  function pollSync(jid) {
    api().getJSON(`/api/pdf/${jid}/sync-status`).then((s) => {
      if (jid !== window.LeIA.currentJobId) return;   // trocou de livro (mas o backend segue)
      if (s.status === "transcribing" || s.status === "aligning") {
        S.status = { has: false, syncing: true, incomplete: false, pct: Math.round((s.progress || 0) * 100) };
        setStatus(`Sincronizando o áudio… ${S.status.pct}%`);
        if (window.LeIA.voices) window.LeIA.voices.render();
        setTimeout(() => pollSync(jid), 1500);
      } else if (s.status === "done") {
        setStatus("");
        S.status = { has: true, syncing: false, incomplete: false, pct: 100 };
        window.LeIA.toast("✅ Áudio sincronizado com o livro!", "success");
        if (jid === window.LeIA.currentJobId && getPref(jid) !== "ai") load(jid);
        if (window.LeIA.voices) window.LeIA.voices.render();
      } else if (s.status === "error") {
        setStatus("");
        S.status = { has: false, syncing: false, incomplete: true, pct: 0 };
        window.LeIA.toast("Erro ao sincronizar: " + (s.error || "desconhecido"), "danger");
        if (window.LeIA.voices) window.LeIA.voices.render();
      } else { setStatus(""); }
    }).catch(() => setTimeout(() => pollSync(jid), 2000));
  }

  function resync(jid) {
    api().postJSON(`/api/pdf/${jid}/resync`, {}).then(() => {
      setStatus("Retomando a sincronização…");
      pollSync(jid);
    }).catch(() => {});
  }

  // trocar para a VOZ HUMANA (áudio importado)
  async function activate(jobId) {
    jobId = jobId || window.LeIA.currentJobId;
    setPref(jobId, "human");
    pl().stop({ keepHighlight: true });
    const ok = await load(jobId);
    if (ok) {
      window.LeIA.toast("🎧 Voz humana (áudio importado)", "success");
      if (window.LeIA.voices) window.LeIA.voices.render();
    }
    return ok;
  }

  // voltar para a VOZ DA IA
  function deactivate() {
    const jid = window.LeIA.currentJobId;
    if (jid) setPref(jid, "ai");
    unload();
    pl().setReady(true);
    if (window.LeIA.voices) { window.LeIA.voices.render(); window.LeIA.voices.updateVoiceLabel(); }
  }

  async function removeSync() {
    const jid = window.LeIA.currentJobId;
    if (!jid) return;
    const ok = await (window.LeIA.confirm ? window.LeIA.confirm({
      title: "Remover áudio sincronizado?",
      message: "O áudio humano importado será apagado. Você volta para a voz da IA.",
      okText: "Remover", danger: true, icon: "🗑️",
    }) : Promise.resolve(true));
    if (!ok) return;
    try { await api().del(`/api/pdf/${jid}/synced-audio`); } catch {}
    setPref(jid, "ai");
    unload();
    S.status = { has: false, syncing: false, incomplete: false, pct: 0 };
    pl().setReady(true);
    window.LeIA.toast("Áudio removido — voltou para a voz da IA", "info");
    if (window.LeIA.voices) window.LeIA.voices.render();
  }

  // ---------------------------------------------------------------- importar
  function pickFile() { const i = $("import-audio-input"); if (i) i.click(); }

  async function importFile(file) {
    const jid = window.LeIA.currentJobId;
    if (!jid) return;
    setPref(jid, "human");
    setStatus("Enviando áudio…");
    S.status = { has: false, syncing: true, incomplete: false, pct: 0 };
    if (window.LeIA.voices) window.LeIA.voices.render();
    const fd = new FormData();
    fd.append("file", file);
    try {
      const resp = await fetch(`/api/pdf/${jid}/import-audio`, { method: "POST", body: fd });
      if (!resp.ok) throw new Error(await resp.text());
      window.LeIA.toast("🎧 Sincronizando o áudio com o texto… pode continuar lendo; avisa quando terminar.", "info");
      pollSync(jid);
    } catch (e) {
      setStatus("");
      S.status = { has: false, syncing: false, incomplete: false, pct: 0 };
      window.LeIA.toast("Falha ao importar: " + (e.message || e), "danger");
    }
  }

  function init() {
    const input = $("import-audio-input");
    if (input) {
      input.addEventListener("change", () => {
        if (input.files && input.files[0]) importFile(input.files[0]);
        input.value = "";
      });
    }
    const btn = $("btn-sync-audio");
    if (btn) {
      btn.addEventListener("click", () => {
        if (S.status.syncing) { window.LeIA.toast("Já estou sincronizando este livro…", "info"); return; }
        if (S.status.has) { activate(); return; }   // já tem áudio → usa a voz humana
        pickFile();                                  // senão → importar
      });
    }
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.synced = {
    init, onOpen, load, unload, isActive, getStatus,
    toggle, play, pause, seekToId, step, seekRatio, setSpeed, setVolume,
    activate, deactivate, removeSync, pickFile,
  };
})();
