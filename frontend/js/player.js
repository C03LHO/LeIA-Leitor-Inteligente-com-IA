(function () {
  let sentences = [];
  let currentIndex = -1;
  let audioQueue = [];
  let audio = null;
  let socket = null;
  let isPlaying = false;
  let voice = "default";

  function setSentences(list) {
    sentences = list;
    currentIndex = -1;
    audioQueue = [];
    if (audio) {
      audio.pause();
      audio = null;
    }
  }

  function getSpeed() {
    return parseFloat(document.getElementById("speed-select").value || "1.0");
  }

  function highlight(index) {
    sentences.forEach((s) => s.el.classList.remove("active"));
    if (index >= 0 && index < sentences.length) {
      const cur = sentences[index];
      cur.el.classList.add("active");
      cur.el.scrollIntoView({ behavior: "smooth", block: "center" });
      document.getElementById("now-reading").textContent = cur.text;
    } else {
      document.getElementById("now-reading").textContent = "—";
    }
  }

  function stop() {
    isPlaying = false;
    if (audio) {
      audio.pause();
      audio = null;
    }
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close();
    }
    socket = null;
    audioQueue = [];
    document.getElementById("btn-play").textContent = "▶";
  }

  function playNextChunk() {
    if (audioQueue.length === 0) {
      if (!socket || socket.readyState === WebSocket.CLOSED) {
        stop();
      }
      return;
    }
    const item = audioQueue.shift();
    currentIndex = item.index;
    highlight(currentIndex);
    audio = new Audio("data:audio/wav;base64," + item.audio_b64);
    audio.playbackRate = 1.0;
    audio.onended = () => {
      if (isPlaying) playNextChunk();
    };
    audio.onerror = () => {
      window.LeIA.toast("Erro reproduzindo áudio", "warning");
      if (isPlaying) playNextChunk();
    };
    audio.play().catch((e) => console.warn("autoplay blocked", e));
  }

  function start() {
    if (sentences.length === 0) {
      window.LeIA.toast("Nenhum texto carregado", "warning");
      return;
    }
    isPlaying = true;
    document.getElementById("btn-play").textContent = "⏸";

    const fromIdx = currentIndex < 0 ? 0 : currentIndex;
    const remainingText = sentences
      .slice(fromIdx)
      .map((s) => s.text)
      .join(" ");

    socket = window.LeIA.api.openTTSSocket();
    socket.onopen = () => {
      socket.send(
        JSON.stringify({ text: remainingText, voice, speed: getSpeed() })
      );
    };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "chunk") {
        const offset = fromIdx + msg.index;
        audioQueue.push({ index: offset, audio_b64: msg.audio_b64 });
        if (!audio || audio.paused || audio.ended) playNextChunk();
      } else if (msg.type === "done") {
        // streaming ended; queue drains on its own
      } else if (msg.type === "error") {
        window.LeIA.toast("TTS: " + msg.message, "danger");
      }
    };
    socket.onerror = () => window.LeIA.toast("WebSocket TTS falhou", "danger");
    socket.onclose = () => {
      if (audioQueue.length === 0 && (!audio || audio.ended)) {
        stop();
      }
    };
  }

  function toggle() {
    if (isPlaying) {
      if (audio && !audio.paused) {
        audio.pause();
        document.getElementById("btn-play").textContent = "▶";
        isPlaying = false;
      } else if (audio && audio.paused) {
        audio.play();
        document.getElementById("btn-play").textContent = "⏸";
        isPlaying = true;
      } else {
        stop();
      }
    } else {
      start();
    }
  }

  function next() {
    stop();
    currentIndex = Math.min(currentIndex + 1, sentences.length - 1);
    highlight(currentIndex);
    start();
  }

  function prev() {
    stop();
    currentIndex = Math.max(currentIndex - 1, 0);
    highlight(currentIndex);
    start();
  }

  function init() {
    document.getElementById("btn-play").addEventListener("click", toggle);
    document.getElementById("btn-next").addEventListener("click", next);
    document.getElementById("btn-prev").addEventListener("click", prev);
    document.getElementById("speed-select").addEventListener("change", () => {
      if (isPlaying) {
        stop();
        start();
      }
    });
  }

  window.LeIA = window.LeIA || {};
  window.LeIA.player = { setSentences, start, stop, toggle, next, prev, initPlayer: init };
})();
