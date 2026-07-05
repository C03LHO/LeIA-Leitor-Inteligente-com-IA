(function () {
  const state = {
    voiceId: "natural",
    speed: 1.0,
    volume: 1.0,
    muted: false,
    isPlaying: false,
    isBuffering: false,
    audioReady: true, // liberado só quando a pré-geração termina
    currentSentenceId: null,
    audioQueue: [],
    bufferedIds: new Set(),
    audio: null,
    socket: null,
    streamDone: false, // o lote (seção) atual terminou de transmitir?
    sectionAudioBlobs: [], // for download
  };

  function setReady(ready) {
    state.audioReady = !!ready;
    const btn = document.getElementById("btn-play");
    if (btn) btn.classList.toggle("locked", !ready);
  }

  function restorePosition(globalIndex) {
    const r = window.LeIA.reader.state;
    if (!r.sentences.length) return;
    const idx = Math.max(0, Math.min(r.sentences.length - 1, parseInt(globalIndex, 10) || 0));
    state.currentSentenceId = r.sentences[idx].id;
    window.LeIA.reader.highlight(state.currentSentenceId);
    updateProgress();
  }

  function saveProgress() {
    const cur = currentSentence();
    if (cur && window.LeIA.saveProgress) window.LeIA.saveProgress(cur.globalIndex);
  }

  function loadPrefs() {
    try {
      const v = localStorage.getItem("leia.voice");
      if (v) state.voiceId = v;
      const sp = parseFloat(localStorage.getItem("leia.speed") || "1.0");
      if (!isNaN(sp)) state.speed = sp;
      const vol = parseFloat(localStorage.getItem("leia.volume") || "1.0");
      if (!isNaN(vol)) state.volume = vol;
      state.muted = localStorage.getItem("leia.muted") === "1";
    } catch {}
  }

  function savePref(k, v) {
    try { localStorage.setItem(k, String(v)); } catch {}
  }

  function setPlayIcon(kind) {
    const playI = document.getElementById("icon-play");
    const pauseI = document.getElementById("icon-pause");
    const loadI = document.getElementById("icon-loading");
    playI.classList.add("hidden");
    pauseI.classList.add("hidden");
    loadI.classList.add("hidden");
    if (kind === "play") playI.classList.remove("hidden");
    else if (kind === "pause") pauseI.classList.remove("hidden");
    else if (kind === "loading") loadI.classList.remove("hidden");
    // Pulso suave no botão só enquanto está de fato narrando.
    const btn = document.getElementById("btn-play");
    if (btn) btn.classList.toggle("playing", kind === "pause");
  }

  function fmtTime(s) {
    if (!isFinite(s) || s < 0) s = 0;
    const m = Math.floor(s / 60);
    const ss = Math.floor(s % 60).toString().padStart(2, "0");
    return `${m}:${ss}`;
  }

  // ~14 caracteres de fala por segundo em pt-BR a 1x → estimativa do tempo restante.
  const CHARS_PER_SEC = 14;
  function fmtDuration(s) {
    s = Math.max(0, Math.round(s));
    if (s < 60) return "menos de 1 min";
    const m = Math.round(s / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60), mm = m % 60;
    return mm ? `${h} h ${mm} min` : `${h} h`;
  }

  function currentSentence() {
    const r = window.LeIA.reader.state;
    return r.sentenceById.get(state.currentSentenceId);
  }

  function currentSection() {
    const s = currentSentence();
    if (!s) return null;
    return window.LeIA.reader.state.sections[s.sectionIndex];
  }

  function currentIndex() {
    const s = currentSentence();
    return s ? s.globalIndex : 0;
  }

  function updateProgress() {
    const r = window.LeIA.reader.state;
    const s = currentSentence();
    const fill = document.getElementById("scrubber-fill");
    const buf = document.getElementById("scrubber-buffer");
    const thumb = document.getElementById("scrubber-thumb");
    const time = document.getElementById("player-time");
    const left = document.getElementById("time-left");
    const total = r.sentences.length;
    if (!s || !total) {
      fill.style.width = "0%";
      buf.style.width = "0%";
      thumb.style.left = "0%";
      time.textContent = "0%";
      if (left) left.textContent = "—";
      return;
    }
    // Progresso ao nível do LIVRO (estilo Kindle), não só da seção.
    const idx = s.globalIndex;
    const pct = (idx / Math.max(1, total - 1)) * 100;
    fill.style.width = pct + "%";
    thumb.style.left = pct + "%";
    // Buffer pronto à frente (livro inteiro).
    let bufferedAhead = 0;
    for (let i = idx; i < total; i++) {
      if (state.bufferedIds.has(r.sentences[i].id)) bufferedAhead++;
      else break;
    }
    buf.style.width = (((idx + bufferedAhead) / total) * 100) + "%";
    // Tempo restante estimado pelos caracteres de fala / velocidade.
    let remChars = 0;
    for (let i = idx; i < total; i++) remChars += r.sentences[i].text.length + 1;
    const secsLeft = remChars / (CHARS_PER_SEC * (state.speed || 1));
    // Tempo restante do capítulo (seção atual).
    const sec = currentSection();
    let chapChars = 0;
    if (sec) for (let i = idx; i < Math.min(sec.sentenceEnd, total); i++) chapChars += r.sentences[i].text.length + 1;
    const chapLeft = chapChars / (CHARS_PER_SEC * (state.speed || 1));
    // % do livro + localização (frase atual / total).
    time.textContent = `${Math.round((idx / total) * 100)}% · ${idx + 1}/${total}`;
    if (left) {
      left.textContent = sec
        ? `${fmtDuration(chapLeft)} no cap. · ${fmtDuration(secsLeft)} restantes`
        : `${fmtDuration(secsLeft)} restantes`;
    }
    updateBookmarkBtn();
  }

  function stop({ keepHighlight = true } = {}) {
    state.isPlaying = false;
    state.isBuffering = false;
    if (state.audio) {
      state.audio.pause();
      state.audio = null;
    }
    if (state.socket && state.socket.readyState === WebSocket.OPEN) {
      try { state.socket.close(); } catch {}
    }
    state.socket = null;
    state.audioQueue = [];
    state.bufferedIds.clear();
    state.streamDone = false;
    setPlayIcon("play");
    if (!keepHighlight) {
      window.LeIA.reader.highlight(null);
    }
    updateProgress();
  }

  function startFromCurrent() {
    const r = window.LeIA.reader.state;
    if (r.sentences.length === 0) {
      window.LeIA.toast("Nenhum texto carregado", "warning");
      return;
    }
    if (!state.currentSentenceId) {
      state.currentSentenceId = r.sentences[0].id;
    }
    const s = r.sentenceById.get(state.currentSentenceId);
    if (!s) return;
    const sec = r.sections[s.sectionIndex];
    const slice = r.sentences.slice(s.globalIndex, sec.sentenceEnd);

    state.isPlaying = true;
    state.isBuffering = true;
    state.streamDone = false;
    state.audioQueue = [];
    state.bufferedIds.clear();
    setPlayIcon("loading");

    // Captura o socket local: se um novo lote (próxima seção) começar, os
    // handlers do socket antigo não devem mais mexer no estado.
    const sock = window.LeIA.api.openTTSSocket();
    state.socket = sock;
    sock.onopen = () => {
      if (state.socket !== sock) return;
      sock.send(JSON.stringify({
        sentences: slice.map((x) => ({ id: x.id, text: x.text })),
        voice: state.voiceId,
      }));
    };
    sock.onmessage = (ev) => {
      if (state.socket !== sock) return;
      const msg = JSON.parse(ev.data);
      if (msg.type === "audio_chunk") {
        state.audioQueue.push(msg);
        state.bufferedIds.add(msg.sentence_id);
        if (!state.audio || state.audio.paused || state.audio.ended) {
          playNext();
        } else {
          updateProgress();
        }
      } else if (msg.type === "error") {
        window.LeIA.toast(
          "Falha ao sintetizar. A GPU pode estar sobrecarregada — tente novamente em alguns segundos.",
          "danger"
        );
      } else if (msg.type === "section_done") {
        state.streamDone = true;
      }
    };
    sock.onerror = () => {
      if (state.socket !== sock) return;
      window.LeIA.toast("WebSocket TTS falhou", "danger");
      stop();
    };
    sock.onclose = () => {
      if (state.socket !== sock) return;
      state.streamDone = true;   // a seção terminou de transmitir
      // Se o áudio já acabou e a fila esvaziou, decide continuar ou parar.
      if (state.isPlaying && state.audioQueue.length === 0 && (!state.audio || state.audio.ended)) {
        playNext();
      }
    };
  }

  function playNext() {
    if (state.audioQueue.length === 0) {
      // Acabou o lote atual. Se a seção terminou de transmitir e ainda há texto,
      // CONTINUA sozinho na próxima seção (antes travava aqui e exigia clique).
      if (state.streamDone && state.isPlaying) {
        const r = window.LeIA.reader.state;
        const cur = r.sentenceById.get(state.currentSentenceId);
        const nextIdx = cur ? cur.globalIndex + 1 : 0;
        if (nextIdx < r.sentences.length) {
          state.currentSentenceId = r.sentences[nextIdx].id;
          startFromCurrent();   // abre novo socket para a próxima seção
          return;
        }
        stop();   // fim do documento
        return;
      }
      state.isBuffering = state.isPlaying; // still expecting
      setPlayIcon(state.isPlaying ? "loading" : "play");
      return;
    }
    const item = state.audioQueue.shift();
    state.currentSentenceId = item.sentence_id;
    window.LeIA.reader.highlight(item.sentence_id);
    updateProgress();
    saveProgress();

    state.audio = new Audio("data:audio/wav;base64," + item.audio_b64);
    state.audio.volume = state.muted ? 0 : state.volume;
    state.audio.playbackRate = state.speed;
    state.audio.onplay = () => {
      state.isBuffering = false;
      setPlayIcon("pause");
    };
    state.audio.onended = () => {
      if (state.isPlaying) playNext();
    };
    state.audio.onerror = () => {
      window.LeIA.toast("Erro reproduzindo áudio", "warning");
      if (state.isPlaying) playNext();
    };
    state.audio.play().catch((err) => {
      console.warn("autoplay blocked", err);
      state.isPlaying = false;
      setPlayIcon("play");
    });
  }

  function toggle() {
    if (!state.isPlaying && !state.audioReady) {
      window.LeIA.toast("⏳ A narração ainda está sendo preparada. Aguarde ficar pronta.", "info");
      return;
    }
    if (!state.isPlaying) {
      startFromCurrent();
    } else if (state.audio && !state.audio.paused) {
      state.audio.pause();
      state.isPlaying = false;
      setPlayIcon("play");
    } else if (state.audio && state.audio.paused) {
      state.audio.play();
      state.isPlaying = true;
      setPlayIcon("pause");
    } else {
      stop();
    }
  }

  function jumpToSentence(sid) {
    const r = window.LeIA.reader.state;
    if (!r.sentenceById.has(sid)) return;
    const wasPlaying = state.isPlaying;
    stop();
    state.currentSentenceId = sid;
    window.LeIA.reader.highlight(sid);
    updateProgress();
    saveProgress();
    if (wasPlaying) startFromCurrent();
  }

  function moveSentence(delta) {
    const r = window.LeIA.reader.state;
    if (r.sentences.length === 0) return;
    const cur = currentSentence();
    const idx = cur ? cur.globalIndex : 0;
    const ni = Math.max(0, Math.min(r.sentences.length - 1, idx + delta));
    jumpToSentence(r.sentences[ni].id);
  }

  function moveSection(delta) {
    const r = window.LeIA.reader.state;
    if (r.sections.length === 0) return;
    const cur = currentSentence();
    let targetSec = cur ? cur.sectionIndex + delta : (delta > 0 ? 0 : 0);
    targetSec = Math.max(0, Math.min(r.sections.length - 1, targetSec));
    const sec = r.sections[targetSec];
    if (!sec) return;
    if (sec.sentenceStart >= r.sentences.length) return;
    jumpToSentence(r.sentences[sec.sentenceStart].id);
  }

  function setSpeed(value) {
    state.speed = value;
    savePref("leia.speed", value); // padrão global (último usado)
    const jid = window.LeIA.currentJobId;
    if (jid != null) savePref("leia.speed." + jid, value); // lembrada por livro
    document.getElementById("speed-label").textContent = value.toFixed(2).replace(/0$/,'') + "x";
    // Velocidade é playbackRate no navegador → muda ao vivo, sem re-sintetizar.
    if (state.audio) state.audio.playbackRate = value;
  }

  // Ao abrir um livro: aplica a velocidade lembrada dele (ou a global) e zera
  // qualquer timer de sono pendente.
  function onDocOpen(jobId) {
    let v = parseFloat(localStorage.getItem("leia.speed." + jobId));
    if (isNaN(v)) v = state.speed;
    setSpeed(v);
    clearSleep(true);
  }

  function bumpSpeed(delta) {
    const opts = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0];
    const i = opts.indexOf(state.speed);
    const ni = Math.max(0, Math.min(opts.length - 1, (i < 0 ? 1 : i) + delta));
    setSpeed(opts[ni]);
  }

  function setVoice(id, label) {
    state.voiceId = id;
    savePref("leia.voice", id);
    if (label) document.getElementById("voice-label").textContent = label;
    if (state.isPlaying) {
      stop();
      startFromCurrent();
    }
  }

  function setVolume(v) {
    state.volume = Math.max(0, Math.min(1, v));
    state.muted = false;
    savePref("leia.volume", state.volume);
    savePref("leia.muted", "0");
    if (state.audio) state.audio.volume = state.volume;
    document.getElementById("volume-slider").value = String(Math.round(state.volume * 100));
    document.getElementById("volume-value").textContent = Math.round(state.volume * 100);
  }

  function bumpVolume(delta) {
    setVolume(state.volume + delta);
  }

  function toggleMute() {
    state.muted = !state.muted;
    savePref("leia.muted", state.muted ? "1" : "0");
    if (state.audio) state.audio.volume = state.muted ? 0 : state.volume;
    window.LeIA.toast(state.muted ? "Mudo" : "Som ativo", "info");
  }

  async function downloadSection() {
    const sec = currentSection();
    const r = window.LeIA.reader.state;
    if (!sec) {
      window.LeIA.toast("Sem seção carregada", "warning");
      return;
    }
    const slice = r.sentences.slice(sec.sentenceStart, sec.sentenceEnd);
    const text = slice.map((x) => x.text).join(" ");
    window.LeIA.toast("Gerando áudio da seção…", "info");
    try {
      const resp = await fetch("/api/tts/synthesize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: state.voiceId }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `leia_${sec.title || "secao"}.wav`.replace(/\s+/g, "_");
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      window.LeIA.toast("Falha no download: " + e.message, "danger");
    }
  }

  function onScrubberClick(e) {
    const r = window.LeIA.reader.state;
    if (!r.sentences.length) return;
    const track = e.currentTarget.querySelector(".scrubber-track");
    const rect = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const idx = Math.min(r.sentences.length - 1, Math.floor(ratio * r.sentences.length));
    jumpToSentence(r.sentences[idx].id);
  }

  // ---------- Marcadores (bookmarks) ----------
  function escHTML(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[c]);
  }
  function bmKey() { return "leia.bm." + (window.LeIA.currentJobId || "x"); }
  function getBookmarks() {
    try { return JSON.parse(localStorage.getItem(bmKey()) || "[]"); } catch { return []; }
  }
  function setBookmarks(arr) {
    try { localStorage.setItem(bmKey(), JSON.stringify(arr)); } catch {}
  }
  function jumpToSentenceIdx(idx) {
    const r = window.LeIA.reader.state;
    if (idx < 0 || idx >= r.sentences.length) return;
    jumpToSentence(r.sentences[idx].id);
  }
  function toggleBookmark() {
    const cur = currentSentence();
    if (!cur) { window.LeIA.toast("Abra um livro primeiro", "warning"); return; }
    const bm = getBookmarks();
    const i = bm.findIndex((b) => b.idx === cur.globalIndex);
    if (i >= 0) { bm.splice(i, 1); window.LeIA.toast("Marcador removido", "info"); }
    else { bm.push({ idx: cur.globalIndex, text: cur.text.slice(0, 90) }); bm.sort((a, b) => a.idx - b.idx); window.LeIA.toast("📑 Posição marcada", "success"); }
    setBookmarks(bm);
    renderBookmarks();
  }
  function renderBookmarks() {
    const r = window.LeIA.reader.state;
    const total = r.sentences.length || 1;
    const scrubber = document.getElementById("scrubber");
    if (scrubber) {
      scrubber.querySelectorAll(".bm-tick").forEach((t) => t.remove());
      getBookmarks().forEach((b) => {
        const tick = document.createElement("div");
        tick.className = "bm-tick";
        tick.style.left = ((b.idx / total) * 100) + "%";
        tick.title = b.text;
        tick.addEventListener("click", (e) => { e.stopPropagation(); jumpToSentenceIdx(b.idx); });
        scrubber.appendChild(tick);
      });
    }
    updateBookmarkBtn();
    renderBookmarkList();
  }
  function updateBookmarkBtn() {
    const cur = currentSentence();
    const btn = document.getElementById("btn-bookmark");
    if (btn) btn.classList.toggle("active", !!(cur && getBookmarks().some((b) => b.idx === cur.globalIndex)));
  }
  function renderBookmarkList() {
    const wrap = document.getElementById("bookmarks-list");
    if (!wrap) return;
    const bm = getBookmarks();
    if (!bm.length) { wrap.innerHTML = `<div class="bm-empty">Nenhum marcador ainda.</div>`; return; }
    const total = window.LeIA.reader.state.sentences.length || 1;
    wrap.innerHTML = "";
    bm.forEach((b) => {
      const item = document.createElement("div");
      item.className = "bm-item";
      item.innerHTML = `<div class="bm-pct">${Math.round((b.idx / total) * 100)}%</div>` +
        `<div class="bm-text">${escHTML(b.text)}</div>` +
        `<button class="bm-del" title="Remover">✕</button>`;
      item.addEventListener("click", (e) => {
        if (e.target.closest(".bm-del")) return;
        jumpToSentenceIdx(b.idx);
        document.getElementById("bookmarks-popover").classList.remove("open");
      });
      item.querySelector(".bm-del").addEventListener("click", (e) => {
        e.stopPropagation();
        setBookmarks(getBookmarks().filter((x) => x.idx !== b.idx));
        renderBookmarks();
      });
      wrap.appendChild(item);
    });
  }

  // ---------- Timer de sono ----------
  let sleepTicker = null, sleepDeadline = 0, sleepChapterStart = null;

  function clearSleep() {
    if (sleepTicker) { clearInterval(sleepTicker); sleepTicker = null; }
    sleepDeadline = 0; sleepChapterStart = null;
    const badge = document.getElementById("sleep-badge");
    if (badge) { badge.classList.add("hidden"); badge.textContent = ""; }
    const btn = document.getElementById("btn-sleep");
    if (btn) btn.classList.remove("active");
  }

  function fireSleep() {
    clearSleep();
    stop();               // mantém a posição (keepHighlight = true por padrão)
    saveProgress();
    window.LeIA.toast("Narração pausada — timer de sono", "info");
  }

  function tickSleep() {
    const badge = document.getElementById("sleep-badge");
    if (sleepChapterStart != null) {
      const cur = currentSentence();
      if (cur && cur.sectionIndex > sleepChapterStart) fireSleep();
      return;
    }
    const remain = sleepDeadline - Date.now();
    if (remain <= 0) { fireSleep(); return; }
    if (badge) {
      const m = Math.floor(remain / 60000), s = Math.floor((remain % 60000) / 1000);
      badge.textContent = m > 0 ? `${m}m` : `${s}s`;
    }
  }

  function setSleep(value) {
    clearSleep();
    const badge = document.getElementById("sleep-badge");
    const btn = document.getElementById("btn-sleep");
    if (value === "0" || value === 0) { window.LeIA.toast("Timer de sono desligado", "info"); return; }
    if (value === "chapter") {
      const cur = currentSentence();
      sleepChapterStart = cur ? cur.sectionIndex : 0;
      sleepTicker = setInterval(tickSleep, 1000);
      if (btn) btn.classList.add("active");
      if (badge) { badge.textContent = "cap"; badge.classList.remove("hidden"); }
      window.LeIA.toast("Vai parar no fim do capítulo", "info");
      return;
    }
    const mins = parseInt(value, 10);
    if (!mins) return;
    sleepDeadline = Date.now() + mins * 60000;
    sleepTicker = setInterval(tickSleep, 1000);
    if (btn) btn.classList.add("active");
    if (badge) badge.classList.remove("hidden");
    tickSleep();
    window.LeIA.toast(`Timer de sono: ${mins} min`, "info");
  }

  function bindPopover(button, popover) {
    function close() { popover.classList.remove("open"); }
    function open() {
      const rect = button.getBoundingClientRect();
      popover.classList.add("open"); // precisa estar visível para medir a largura
      const pw = popover.offsetWidth || 160;
      let left = rect.left + rect.width / 2 - pw / 2; // centraliza sobre o botão
      left = Math.max(8, Math.min(left, window.innerWidth - pw - 8)); // prende na tela
      popover.style.left = `${left}px`;
      popover.style.bottom = `calc(100vh - ${rect.top - 8}px)`;
    }
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      if (popover.classList.contains("open")) close();
      else open();
    });
    document.addEventListener("click", (e) => {
      if (!popover.contains(e.target) && e.target !== button) close();
    });
  }

  function initPlayer() {
    loadPrefs();
    document.getElementById("speed-label").textContent =
      state.speed.toFixed(2).replace(/0$/, "") + "x";
    document.getElementById("volume-slider").value = String(Math.round(state.volume * 100));
    document.getElementById("volume-value").textContent = Math.round(state.volume * 100);

    document.getElementById("btn-play").addEventListener("click", toggle);
    document.getElementById("btn-prev").addEventListener("click", () => moveSentence(-1));
    document.getElementById("btn-next").addEventListener("click", () => moveSentence(+1));
    document.getElementById("btn-prev-section").addEventListener("click", () => moveSection(-1));
    document.getElementById("btn-next-section").addEventListener("click", () => moveSection(+1));
    document.getElementById("btn-download").addEventListener("click", downloadSection);
    document.getElementById("scrubber").addEventListener("click", onScrubberClick);
    document.getElementById("btn-bookmark").addEventListener("click", toggleBookmark);
    bindPopover(document.getElementById("btn-bookmarks"), document.getElementById("bookmarks-popover"));

    // Contabiliza tempo de leitura (escuta) para as estatísticas.
    setInterval(() => {
      if (state.isPlaying && state.audio && !state.audio.paused && window.LeIA.stats) {
        window.LeIA.stats.addSeconds(1);
      }
    }, 1000);

    // Speed popover
    const speedBtn = document.getElementById("btn-speed");
    const speedPop = document.getElementById("speed-popover");
    bindPopover(speedBtn, speedPop);
    speedPop.querySelectorAll(".popover-item").forEach((it) => {
      it.addEventListener("click", () => {
        setSpeed(parseFloat(it.dataset.speed));
        speedPop.classList.remove("open");
      });
    });

    // Sleep timer popover
    const sleepPop = document.getElementById("sleep-popover");
    bindPopover(document.getElementById("btn-sleep"), sleepPop);
    sleepPop.querySelectorAll(".popover-item").forEach((it) => {
      it.addEventListener("click", () => {
        setSleep(it.dataset.sleep);
        sleepPop.classList.remove("open");
      });
    });

    // Volume popover
    const volBtn = document.getElementById("btn-volume");
    const volPop = document.getElementById("volume-popover");
    bindPopover(volBtn, volPop);
    document.getElementById("volume-slider").addEventListener("input", (e) => {
      setVolume(parseInt(e.target.value, 10) / 100);
    });

    // Sentence click → jump
    window.addEventListener("leia:sentence-click", (e) => jumpToSentence(e.detail.sid));

    // Shortcuts
    const sc = window.LeIA.shortcuts;
    sc.on(" ", toggle);
    sc.on("ArrowLeft", () => moveSentence(-1));
    sc.on("ArrowRight", () => moveSentence(+1));
    sc.on("Shift+ArrowLeft", () => moveSection(-1));
    sc.on("Shift+ArrowRight", () => moveSection(+1));
    sc.on("ArrowUp", () => bumpVolume(0.05));
    sc.on("ArrowDown", () => bumpVolume(-0.05));
    sc.on("m", toggleMute);
    sc.on("M", toggleMute);
    sc.on("b", toggleBookmark);
    sc.on("B", toggleBookmark);
    sc.on("+", () => bumpSpeed(+1));
    sc.on("=", () => bumpSpeed(+1));
    sc.on("-", () => bumpSpeed(-1));
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.player = {
    initPlayer, stop, toggle, jumpToSentence, moveSentence, moveSection,
    setSpeed, setVoice, setVolume, toggleMute, setReady, restorePosition, currentIndex,
    renderBookmarks, setSleep, onDocOpen, state,
  };
})();
